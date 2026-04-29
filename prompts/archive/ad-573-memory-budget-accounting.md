# AD-573: Memory Budget Accounting & Context Compression

**Status:** Ready for builder
**Depends on:** None
**Issue:** #360

## Problem Statement

No explicit token budget tracking across recall strategy tiers. `recall_weighted()` has a `context_budget` parameter (default 4000 chars) but no coordination across multiple recall paths. When a cognitive cycle invokes semantic recall, anchor recall, and oracle recall independently, each path consumes tokens without awareness of what others have used. This leads to context overflow or wasted budget.

The existing `MemoryConfig.recall_tiers` (basic/enhanced/full/oracle at line 456 of `src/probos/config.py`) define per-tier budgets but there is no runtime manager that tracks actual consumption and coordinates allocation.

## Implementation

### Add MemoryBudgetConfig

File: `src/probos/config.py`

Add after `WorkingMemoryConfig` (line 785):

```python
class MemoryBudgetConfig(BaseModel):
    """AD-573: Memory budget accounting across recall tiers."""
    enabled: bool = True
    total_budget_tokens: int = 4650
    l0_budget: int = 150    # pinned knowledge (AD-579a)
    l1_budget: int = 3000   # relevant recall (primary semantic + anchor)
    l2_budget: int = 1000   # background/secondary recall
    l3_budget: int = 500    # oracle/cross-agent recall
```

### Add MemoryBudgetManager Class

File: `src/probos/cognitive/memory_budget.py` (new file)

```python
"""AD-573: Memory budget accounting across recall tiers.

Tracks token budget allocation and consumption per tier within a single
cognitive cycle. Reset at the start of each cycle. Tiers are strings
matching the L0/L1/L2/L3 model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import MemoryBudgetConfig

logger = logging.getLogger(__name__)


class MemoryBudgetManager:
    """Per-cycle token budget tracker for memory recall tiers.

    Each tier has an independent budget. Allocations return the granted
    amount (which may be less than requested when budget is exhausted).
    The manager is reset at the start of each cognitive cycle.
    """

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
        """Request token budget from a tier. Returns granted amount.

        If disabled, returns requested (no limiting).
        If tier is unknown, returns 0.
        Granted amount is min(requested, remaining for tier).
        """

    def release(self, tier: str, used: int) -> None:
        """Release unused budget back to a tier.

        Call when actual consumption was less than allocated.
        consumed = max(0, consumed - released).
        """

    def remaining(self, tier: str) -> int:
        """Current remaining budget for a specific tier.

        Returns 0 for unknown tiers. Returns tier budget if disabled.
        """

    def total_remaining(self) -> int:
        """Total remaining budget across all tiers."""

    def reset(self) -> None:
        """Reset all tier consumption to zero. Called per cognitive cycle."""
```

Key behaviors:
- `allocate()`: records consumption, returns `min(requested, remaining)`. When disabled, returns `requested` unchanged.
- `release()`: decrements consumption (clamped to 0). When disabled, no-op.
- `remaining()`: `tier_budget - tier_consumed`. When disabled, returns full tier budget.
- `total_remaining()`: sum of `remaining()` across all tiers.
- `reset()`: zeros all `_tier_consumed`. Does NOT change `_tier_budgets`.
- Unknown tier names: `allocate()` returns 0, `remaining()` returns 0, `release()` is a no-op. Log a warning.

### Add compress_episodes() Helper

File: `src/probos/cognitive/memory_budget.py`

```python
def compress_episodes(episodes: list[RecallScore], budget: int) -> list[RecallScore]:
    """AD-573: Truncate episode list to fit within a token budget.

    Keeps episodes in descending composite_score order. Estimates tokens
    per episode as len(episode.episode.user_input) // CHARS_PER_TOKEN.
    Stops adding when the next episode would exceed budget.

    Args:
        episodes: RecallScore list, assumed pre-sorted by composite_score descending.
        budget: maximum tokens to include.

    Returns:
        Subset of episodes fitting within budget, maintaining order.
    """
```

Use `CHARS_PER_TOKEN = 4` (import from `probos.cognitive.agent_working_memory` or define locally to avoid circular import — define locally is safer).

Logic:
1. Sort by `composite_score` descending (defensive — caller may have pre-sorted).
2. Accumulate token estimates. Stop when next episode would exceed budget.
3. Return the included subset.

### Wire into CognitiveAgent

File: `src/probos/cognitive/cognitive_agent.py`

This is a **lightweight** wiring — do NOT refactor `_build_user_message()`. Add:

1. Import `MemoryBudgetManager` and `MemoryBudgetConfig` with `TYPE_CHECKING` guard.
2. `CognitiveAgent.__init__` uses `**kwargs`. Extract budget config via `self._memory_budget_config = kwargs.get("memory_budget_config")`.
   **Do NOT add an explicit named parameter** — the constructor uses `**kwargs` for optional dependencies.
4. In the `decide()` method, at the start (before `_build_user_message`), create a per-cycle budget manager:

```python
# AD-573: Per-cycle memory budget tracking
_budget_mgr = None
if self._memory_budget_config and self._memory_budget_config.enabled:
    from probos.cognitive.memory_budget import MemoryBudgetManager
    _budget_mgr = MemoryBudgetManager(self._memory_budget_config)
```

Store as a local variable, not an instance attribute — it is per-cycle.

**Do NOT modify `_build_user_message()` in this AD.** The budget manager is created and available for future ADs to pass into recall calls. This AD establishes the accounting infrastructure; future ADs wire it into specific recall paths.

## Acceptance Criteria

1. `MemoryBudgetManager` correctly tracks allocation and consumption per tier.
2. `allocate()` returns granted amount capped at remaining budget.
3. `release()` returns budget for reuse.
4. `remaining()` and `total_remaining()` report accurate state.
5. `reset()` clears all consumption.
6. Unknown tier names handled gracefully (return 0, log warning).
7. When `enabled=False`, all operations are pass-through (no limiting).
8. `compress_episodes()` truncates by composite_score within token budget.
9. `MemoryBudgetConfig` with Pydantic validation and sensible defaults.
10. `CognitiveAgent` accepts optional config and creates per-cycle manager in `decide()`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Test Plan

File: `tests/test_ad573_memory_budget.py`

14 tests:

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_allocate_within_budget` | Requesting less than remaining returns full request |
| 2 | `test_allocate_exceeds_budget` | Requesting more than remaining returns only remaining |
| 3 | `test_release_returns_budget` | After release, remaining increases by released amount |
| 4 | `test_remaining_tracking` | `remaining()` decreases after allocate, increases after release |
| 5 | `test_total_remaining` | `total_remaining()` sums all tiers correctly |
| 6 | `test_reset_restores_full` | After `reset()`, all tiers have full budget |
| 7 | `test_tier_isolation` | Allocating from L1 does not affect L2 budget |
| 8 | `test_compress_episodes_within_budget` | Episodes fitting budget are all returned |
| 9 | `test_compress_episodes_over_budget` | Excess episodes truncated by lowest composite_score |
| 10 | `test_config_defaults` | `MemoryBudgetConfig()` has expected default values |
| 11 | `test_disabled_config_passthrough` | When `enabled=False`, `allocate()` returns full request |
| 12 | `test_budget_per_cycle_reset` | Reset between cycles restores full budget |
| 13 | `test_multiple_allocations_same_tier` | Sequential allocations from same tier accumulate correctly |
| 14 | `test_unknown_tier_returns_zero` | `allocate("nonexistent", 100)` returns 0, `remaining("nonexistent")` returns 0 |

For `compress_episodes` tests, construct `RecallScore` objects with varying `composite_score` and `user_input` lengths. For budget manager tests, use direct instantiation with `MemoryBudgetConfig()`.

Run targeted: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad573_memory_budget.py -v`

## Do Not Build

- No LLM-based summarization or compression. `compress_episodes()` only truncates by score.
- No cross-cycle budget persistence. Manager is per-cycle only.
- No dynamic budget reallocation between tiers (e.g., shifting unused L0 to L1).
- No modification to `_build_user_message()` — budget manager is created but not wired into recall paths yet.
- No changes to `recall_weighted()` — that wiring is a future AD.
- No changes to `render_context()` — working memory has its own budget system.

## Tracker Updates

- `PROGRESS.md`: Add `AD-573 Memory Budget Accounting — CLOSED` under Memory Architecture
- `DECISIONS.md`: Add entry: "AD-573: Added MemoryBudgetManager for per-cycle token budget tracking across 4 tiers (L0 pinned 150, L1 relevant 3000, L2 background 1000, L3 oracle 500). compress_episodes() truncates recall results by composite_score. Infrastructure only — recall path wiring is a future AD."
- `docs/development/roadmap.md`: Update AD-573 row to COMPLETE
- Issue: #360
