"""AD-633c: Speculation Budget — separate token pool with flush-rate feedback.

Per-agent rolling-window budget. Distinct from operational tokens (AD-617).
Standard-tier speculation requires EarnedAgency >= EXECUTING. Cheap and
ZERO_COST tiers are unrestricted by agency. Anticipatory tier is reserved
for AD-633f and defaults to gated.

Flush-rate feedback: when 1-hour rolling flush rate >= threshold (default
0.30), the agent's effective budget halves for the next window. Recovers
on the next window if flush rate drops.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

from probos.cognitive.predictive_branching.engine import ConfidenceTier

logger = logging.getLogger(__name__)


@dataclass
class _AgentBudgetState:
    window_start: float
    tokens_consumed: int = 0
    halved: bool = False


class SpeculationBudget:
    """AD-633c: Per-agent rolling-window token budget with flush-rate feedback."""

    # Agency levels that unlock Standard-tier speculation. Lowercase strings to
    # match probos.earned_agency.AgencyLevel.value canonical form (verified at
    # src/probos/earned_agency.py:11-17 — REACTIVE/SUGGESTIVE/AUTONOMOUS/UNRESTRICTED).
    # Commander-tier and above gets Standard speculation; Lieutenants get Cheap only.
    STANDARD_TIER_AGENCY_LEVELS: frozenset[str] = frozenset({"autonomous", "unrestricted"})

    def __init__(
        self,
        *,
        tokens_per_window: int,
        window_seconds: float,
        flush_rate_threshold: float,
        flush_rate_window_seconds: float,
    ) -> None:
        if tokens_per_window < 0:
            raise ValueError("tokens_per_window must be >= 0")
        if window_seconds < 1.0:
            raise ValueError("window_seconds must be >= 1.0")
        self._tokens_per_window = int(tokens_per_window)
        self._window_seconds = float(window_seconds)
        self._flush_rate_threshold = float(flush_rate_threshold)
        self._flush_rate_window = float(flush_rate_window_seconds)
        self._states: dict[str, _AgentBudgetState] = {}
        # Per-agent outcome ring for flush-rate computation:
        # entries are (timestamp, was_flushed_or_error_bool)
        self._outcomes: dict[str, deque[tuple[float, bool]]] = {}

    def try_reserve(
        self,
        *,
        agent_id: str,
        tokens: int,
        tier: ConfidenceTier,
        agency_level: str | None = None,
    ) -> bool:
        """Attempt to reserve tokens. Returns True iff the reservation fits."""
        if tier == ConfidenceTier.ZERO_COST:
            return False  # ZERO_COST never dispatches speculation
        if tier == ConfidenceTier.ANTICIPATORY:
            # AD-633f reserved — Anticipatory speculation requires the
            # IdleSpeculationPolicy seam; v1 default-no-op never reaches here
            # via the operational path. Defensive deny.
            return False
        if tier == ConfidenceTier.STANDARD:
            if agency_level is None or agency_level.lower() not in self.STANDARD_TIER_AGENCY_LEVELS:
                return False

        now = time.time()
        state = self._states.get(agent_id)
        if state is None or (now - state.window_start) >= self._window_seconds:
            state = _AgentBudgetState(window_start=now, tokens_consumed=0)
            state.halved = self._should_halve(agent_id, now)
            self._states[agent_id] = state

        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        if state.tokens_consumed + tokens > effective_budget:
            return False
        # Reserve optimistically; record_consumption will reconcile on actual usage
        state.tokens_consumed += tokens
        return True

    def record_consumption(self, *, agent_id: str, tokens: int) -> None:
        """Reconcile actual token usage against the optimistic reservation."""
        state = self._states.get(agent_id)
        if state is None:
            return
        # If actual usage exceeded reserve, just clamp to budget — don't overflow
        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        state.tokens_consumed = min(effective_budget, max(0, int(tokens)))

    def record_outcome(self, *, agent_id: str, was_flushed: bool) -> None:
        """Record whether the most recent speculation was flushed/errored.

        ``was_flushed=True`` for FLUSHED and ERROR outcomes (both indicate
        wasted compute); ``False`` for HIT.
        """
        ring = self._outcomes.setdefault(agent_id, deque(maxlen=200))
        ring.append((time.time(), bool(was_flushed)))
        # Prune entries older than flush_rate_window
        cutoff = time.time() - self._flush_rate_window
        while ring and ring[0][0] < cutoff:
            ring.popleft()

    def get_flush_rate(self, agent_id: str) -> float:
        """1-hour rolling flush rate in [0.0, 1.0]. 0.0 if no samples."""
        ring = self._outcomes.get(agent_id)
        if not ring:
            return 0.0
        cutoff = time.time() - self._flush_rate_window
        recent = [w for ts, w in ring if ts >= cutoff]
        if not recent:
            return 0.0
        return sum(1 for w in recent if w) / len(recent)

    def get_remaining_tokens(self, agent_id: str) -> int:
        """Tokens remaining in the agent's current window."""
        state = self._states.get(agent_id)
        if state is None:
            return self._tokens_per_window
        now = time.time()
        if (now - state.window_start) >= self._window_seconds:
            return self._tokens_per_window
        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        return max(0, effective_budget - state.tokens_consumed)

    def _should_halve(self, agent_id: str, now: float) -> bool:
        """Apply flush-rate feedback to the new window."""
        return self.get_flush_rate(agent_id) >= self._flush_rate_threshold
