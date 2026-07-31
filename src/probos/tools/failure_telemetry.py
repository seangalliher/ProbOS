"""AD-1168: per-tool failure telemetry.

``unknown browser action: 'key_type'`` fired twice inside one turn and recurred
across four sessions before anyone noticed. **Nothing counted it, once.**

The pieces that look like they should have caught it do not. AD-571b's
``OperationalStatusTracker`` aggregates by AGENT, so a tool broken for everyone
reads as several agents having a bad day. ``FailureDistiller`` clusters episode
failures, which is a different altitude. Neither can answer "is this tool
behaving as advertised?", because neither is keyed on the tool.

So this is keyed on ``(tool_id, error signature)`` — the pair that distinguishes
"one agent used it badly" from "it is broken for everyone". The signature reuses
AD-1169's ``error_signature``, so a pattern counted here and a fault filed there
carry the same identity and can be joined.

Deliberately synchronous and in-memory. It hangs off the AD-448 post-hook, which
runs inline on every tool invocation, so it must cost effectively nothing and
must never raise into the caller. Durable recording is AD-1169's job; this
answers "how often, how recently" and raises a hand when a pattern forms.

The success path does no work beyond one branch.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque
from typing import Any, Callable

from probos.fault_report import error_signature

logger = logging.getLogger(__name__)

# How many occurrences within the window before this is a pattern rather than a
# transient. Two matches AD-1170's detector: once is a timeout or a race, twice
# is the same tool answering the same way.
DEFAULT_PATTERN_THRESHOLD: int = 2

# Occurrences older than this stop counting toward a pattern. A tool that failed
# twice in a week is not the same signal as one that failed twice in a minute.
DEFAULT_WINDOW_SECONDS: float = 900.0

# Distinct signatures tracked. Bounded because error text is attacker- and
# LLM-influenced: a tool failing with a unique message every call would
# otherwise grow this without limit. Least-recently-seen is evicted first.
DEFAULT_MAX_SIGNATURES: int = 512

# Occurrence timestamps kept per signature. The count is what matters, not the
# history, so this only needs to reach the threshold plus headroom.
_MAX_SAMPLES_PER_SIGNATURE: int = 64


class ToolFailureTelemetry:
    """Bounded per-(tool, error) failure counter over a rolling window."""

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_PATTERN_THRESHOLD,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_signatures: int = DEFAULT_MAX_SIGNATURES,
        emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._window = max(0.0, float(window_seconds))
        self._max_signatures = max(1, int(max_signatures))
        self._emit_fn = emit_fn
        self._clock = clock
        # signature -> (tool_id, deque[timestamp]). OrderedDict so eviction is
        # least-recently-seen rather than arbitrary.
        self._seen: OrderedDict[str, tuple[str, deque[float]]] = OrderedDict()
        # Signatures already reported, so one forming pattern emits once rather
        # than on every subsequent failure.
        self._announced: set[str] = set()

    def record_failure(self, *, tool_id: str, error_text: str) -> int:
        """Note one failure. Returns the occurrence count inside the window."""
        signature = error_signature(tool_id=tool_id, error_text=error_text)
        now = self._clock()

        entry = self._seen.get(signature)
        if entry is None:
            entry = (str(tool_id or ""), deque(maxlen=_MAX_SAMPLES_PER_SIGNATURE))
            self._seen[signature] = entry
        else:
            self._seen.move_to_end(signature)
        stamps = entry[1]
        stamps.append(now)

        if self._window > 0.0:
            cutoff = now - self._window
            while stamps and stamps[0] < cutoff:
                stamps.popleft()

        while len(self._seen) > self._max_signatures:
            evicted, _ = self._seen.popitem(last=False)
            self._announced.discard(evicted)

        count = len(stamps)
        if count >= self._threshold and signature not in self._announced:
            self._announced.add(signature)
            self._emit_pattern(
                signature=signature,
                tool_id=entry[0],
                error_text=error_text,
                count=count,
            )
        return count

    def count_for(self, *, tool_id: str, error_text: str) -> int:
        signature = error_signature(tool_id=tool_id, error_text=error_text)
        entry = self._seen.get(signature)
        return 0 if entry is None else len(entry[1])

    def snapshot(self) -> list[dict[str, Any]]:
        """Current patterns, most frequent first. For introspection and the HXI."""
        return sorted(
            (
                {
                    "signature": sig,
                    "tool_id": tool_id,
                    "occurrences": len(stamps),
                    "last_seen_at": stamps[-1] if stamps else 0.0,
                    "announced": sig in self._announced,
                }
                for sig, (tool_id, stamps) in self._seen.items()
                if stamps
            ),
            key=lambda row: (row["occurrences"], row["last_seen_at"]),
            reverse=True,
        )

    def _emit_pattern(
        self, *, signature: str, tool_id: str, error_text: str, count: int,
    ) -> None:
        logger.warning(
            "AD-1168: tool %r has failed %d times the same way inside the "
            "window; this looks like the tool rather than the caller: %s",
            tool_id, count, str(error_text)[:200],
        )
        if self._emit_fn is None:
            return
        try:
            from probos.events import EventType

            self._emit_fn(
                EventType.TOOL_FAILURE_PATTERN,
                {
                    "tool_id": tool_id,
                    "signature": signature,
                    "occurrences": count,
                    "error": str(error_text)[:500],
                    "timestamp": self._clock(),
                },
            )
        except Exception:
            logger.debug(
                "AD-1168: could not emit the failure-pattern event for %r",
                tool_id, exc_info=True,
            )


def make_failure_telemetry_hook(
    telemetry: ToolFailureTelemetry,
) -> Callable[[dict[str, Any], Any], None]:
    """AD-448 post-hook that feeds failures into ``telemetry``.

    Successes return after one attribute read. ``ToolExecutor`` already wraps
    every post-hook in try/except, so a fault here degrades to "no telemetry"
    and can never turn a working tool call into a failed one — but the guard is
    kept anyway, because this hook runs on the hot path for every invocation.
    """

    def failure_hook(ctx: dict[str, Any], result: Any) -> None:
        error = getattr(result, "error", None)
        if error is None:
            return
        try:
            telemetry.record_failure(
                tool_id=str(ctx.get("tool_id", "")), error_text=str(error),
            )
        except Exception:
            logger.debug("AD-1168: failure telemetry hook raised", exc_info=True)

    return failure_hook
