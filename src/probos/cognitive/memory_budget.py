"""AD-573: Memory budget accounting across recall tiers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from probos.types import RecallScore

if TYPE_CHECKING:
    from probos.config import MemoryBudgetConfig

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


class MemoryBudgetManager:
    """Per-cycle token budget tracker for memory recall tiers."""

    def __init__(self, config: MemoryBudgetConfig) -> None:
        self._config = config
        self._enabled = config.enabled
        self._tier_budgets: dict[str, int] = {}
        self._tier_consumed: dict[str, int] = {}
        self._initialize_tiers()

    def _initialize_tiers(self) -> None:
        """Set up tier budgets from config."""
        self._tier_budgets = {
            "l0": self._config.l0_budget,
            "l1": self._config.l1_budget,
            "l2": self._config.l2_budget,
            "l3": self._config.l3_budget,
        }
        self._tier_consumed = {tier: 0 for tier in self._tier_budgets}

    def allocate(self, tier: str, requested: int) -> int:
        """Request token budget from a tier and return the granted amount."""
        if not self._enabled:
            return requested
        if tier not in self._tier_budgets:
            logger.warning(
                "AD-573: Unknown memory budget tier %s; returning zero allocation. "
                "Caller should use l0, l1, l2, or l3.",
                tier,
            )
            return 0
        remaining = self.remaining(tier)
        granted = min(max(requested, 0), remaining)
        self._tier_consumed[tier] += granted
        return granted

    def release(self, tier: str, used: int) -> None:
        """Release unused budget back to a tier."""
        if not self._enabled:
            return
        if tier not in self._tier_budgets:
            logger.warning(
                "AD-573: Unknown memory budget tier %s during release; no budget changed. "
                "Caller should use l0, l1, l2, or l3.",
                tier,
            )
            return
        released = max(used, 0)
        self._tier_consumed[tier] = max(0, self._tier_consumed[tier] - released)

    def remaining(self, tier: str) -> int:
        """Return current remaining budget for a specific tier."""
        if tier not in self._tier_budgets:
            return 0
        if not self._enabled:
            return self._tier_budgets[tier]
        return max(0, self._tier_budgets[tier] - self._tier_consumed[tier])

    def total_remaining(self) -> int:
        """Return total remaining budget across all tiers."""
        return sum(self.remaining(tier) for tier in self._tier_budgets)

    def reset(self) -> None:
        """Reset all tier consumption to zero."""
        self._tier_consumed = {tier: 0 for tier in self._tier_budgets}


def compress_episodes(episodes: list[RecallScore], budget: int) -> list[RecallScore]:
    """Truncate recall results to fit within a token budget."""
    if budget <= 0:
        return []
    sorted_episodes = sorted(
        episodes,
        key=lambda recall_score: recall_score.composite_score,
        reverse=True,
    )
    included: list[RecallScore] = []
    consumed = 0
    for recall_score in sorted_episodes:
        estimated_tokens = len(recall_score.episode.user_input) // CHARS_PER_TOKEN
        if consumed + estimated_tokens > budget:
            break
        included.append(recall_score)
        consumed += estimated_tokens
    return included