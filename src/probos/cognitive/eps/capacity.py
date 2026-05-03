"""AD-469: CapacityTracker -- rolling-window aggregator over CognitiveJournal."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapacitySummary:
    """Snapshot of ProbOS LLM capacity over the configured window."""

    window_seconds: float
    total_tokens: int
    total_calls: int
    tokens_per_minute: float
    calls_per_minute: float
    by_agent: dict[str, int] = field(default_factory=dict)
    by_tier: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, int] = field(default_factory=dict)


class CapacityTracker:
    """Read-only aggregator over CognitiveJournal.

    v1 surface:
      - ``summary()`` -> ``CapacitySummary`` (tokens/calls + by-agent/tier/model maps).

    Stateless. Each call queries the journal afresh; no caching.

    v1 reports an unfiltered aggregate (no time-window filter on the
    journal query). When the journal extends beyond the configured
    window, ``tokens_per_minute`` over-states the current rate by the
    journal-depth/window-depth ratio. AD-469b will introduce a
    ``since=`` filter via ``get_token_usage_by`` extension. Documented
    as honest deferral.
    """

    DEFAULT_WINDOW_SECONDS = 60.0

    def __init__(
        self,
        *,
        runtime: Any,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        # AD-469: getattr defensive read for __new__-bypass tests (convention #11).
        self._runtime = runtime
        self._window_seconds = window_seconds

    async def summary(self) -> CapacitySummary:
        rt = getattr(self, "_runtime", None)
        empty = CapacitySummary(
            window_seconds=self._window_seconds,
            total_tokens=0,
            total_calls=0,
            tokens_per_minute=0.0,
            calls_per_minute=0.0,
        )
        if rt is None:
            return empty
        journal = getattr(rt, "cognitive_journal", None)
        if journal is None:
            return empty

        # AD-469 rev: real journal API is `get_token_usage_by(group_by=...)`
        # (verified at journal.py:299). Returns list[dict] with keys:
        # {<group_by>: <key>, "total_calls", "total_tokens",
        #  "prompt_tokens", "completion_tokens", "avg_latency_ms"}.
        # Note: dict-key access depends on group_by argument value.
        try:
            by_agent = await journal.get_token_usage_by(group_by="agent_id")
            by_tier = await journal.get_token_usage_by(group_by="tier")
            by_model = await journal.get_token_usage_by(group_by="model")
        except Exception:
            logger.warning(
                "AD-469: get_token_usage_by failed; returning empty summary",
                exc_info=True,
            )
            return empty

        total_tokens = sum(
            int(row.get("total_tokens", 0) or 0) for row in by_agent
        )
        total_calls = sum(int(row.get("total_calls", 0) or 0) for row in by_agent)
        per_min = (
            (total_tokens / self._window_seconds) * 60.0
            if self._window_seconds > 0 else 0.0
        )
        calls_per_min = (
            (total_calls / self._window_seconds) * 60.0
            if self._window_seconds > 0 else 0.0
        )

        return CapacitySummary(
            window_seconds=self._window_seconds,
            total_tokens=total_tokens,
            total_calls=total_calls,
            tokens_per_minute=per_min,
            calls_per_minute=calls_per_min,
            by_agent={
                str(row.get("agent_id", "") or ""): int(row.get("total_tokens", 0) or 0)
                for row in by_agent
            },
            by_tier={
                str(row.get("tier", "") or ""): int(row.get("total_tokens", 0) or 0)
                for row in by_tier
            },
            by_model={
                str(row.get("model", "") or ""): int(row.get("total_tokens", 0) or 0)
                for row in by_model
            },
        )
