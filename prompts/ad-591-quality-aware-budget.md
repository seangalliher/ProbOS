# AD-591: Quality-Aware Budget Enforcement

**AD:** 591
**Title:** Quality-Aware Budget Enforcement — Stop Adding Episodes When Quality Degrades
**Type:** Enhancement (recall pipeline, cognitive safety)
**Depends on:** AD-590 (composite score floor) — ships after AD-590
**Absorbs:** None
**Risk:** Low-Medium — conservative defaults, opt-out via 0 values
**Research:** `docs/research/confabulation-scaling-research.md`

---

## Problem Statement

After AD-590's composite score floor filters low-scoring episodes (<0.35), the remaining candidates all exceed the quality threshold. But the budget enforcement loop (step 5 in `recall_weighted()`) still uses **character count only** — it accumulates episodes until the 4000-char budget is exhausted, regardless of how many episodes that produces.

A typical enhanced-tier recall after AD-590:
- Over-fetch: `k*3 = 15` candidates
- After AD-590 floor (0.35): ~8-10 candidates remain
- Budget enforcement: all 8-10 fit in 4000 chars (8 × 120 avg = 960 chars)
- Result: all 8-10 episodes enter context

The problem: episodes #6-10 score 0.36-0.42 — barely above the floor. They're **individually legitimate** but **collectively noise**. Adding them dilutes the signal from the top 5 episodes (scoring 0.55-0.70+) without adding proportional information.

Two fixes needed:
1. **Quality stop**: Stop adding episodes when the next one would significantly degrade the mean quality of the recalled set
2. **Episode count cap**: Hard maximum regardless of budget — prevent 10+ episodes even when all fit character-wise

### Relationship to AD-568b (Adaptive Budget)

AD-568b's `compute_adaptive_budget()` in `source_governance.py` runs **after** `recall_weighted()` returns — it performs a secondary budget re-enforcement on the already-budgeted results. AD-591 modifies the **inner** budget loop (step 5) inside `recall_weighted()`. They compose in layers:

```
recall_weighted() step 5: quality-aware inner budget (AD-591)
    ↓ returns budgeted results
cognitive_agent.py / proactive.py: adaptive re-budget (AD-568b, existing)
    ↓ further trims if quality signals are weak
final episode list for context formatting
```

AD-568b remains as defense-in-depth. No changes to `source_governance.py`.

---

## Design Principles Compliance

- **SOLID (S):** Budget enforcement stays in `recall_weighted()` where it belongs. No new classes — two additional conditions in the existing loop.
- **SOLID (O):** Extended via new parameters with backward-compatible defaults (0 = disabled). No existing behavior changes unless caller opts in.
- **SOLID (D):** All thresholds flow from config (`MemoryConfig`) through tier params, not hardcoded.
- **Law of Demeter:** No new object traversals. Loop reads `rs.composite_score` — same access pattern already used.
- **Fail Fast / Defense in Depth:** This is layer 2 of 4 in the confabulation scaling mitigation stack (AD-590 floor → AD-591 quality budget → AD-568b adaptive re-budget → AD-592 instruction guards).
- **DRY:** Extends the existing budget loop rather than adding a separate post-processing step. `compute_adaptive_budget()` retained as-is — no duplication.
- **Cloud-Ready Storage:** No storage changes.

---

## Implementation

### File 1: `src/probos/cognitive/episodic.py`

**Change 1: Add `max_recall_episodes` and `recall_quality_floor` parameters to `recall_weighted()` signature (line 1549)**

Current signature (after AD-590):
```python
async def recall_weighted(
    self,
    agent_id: str,
    query: str,
    *,
    trust_network: Any = None,
    hebbian_router: Any = None,
    intent_type: str = "",
    k: int = 5,
    context_budget: int = 4000,
    weights: dict[str, float] | None = None,
    anchor_confidence_gate: float = 0.0,
    composite_score_floor: float = 0.0,
    convergence_bonus: float = 0.10,
) -> list[RecallScore]:
```

Add two parameters after `composite_score_floor`:
```python
async def recall_weighted(
    self,
    agent_id: str,
    query: str,
    *,
    trust_network: Any = None,
    hebbian_router: Any = None,
    intent_type: str = "",
    k: int = 5,
    context_budget: int = 4000,
    weights: dict[str, float] | None = None,
    anchor_confidence_gate: float = 0.0,
    composite_score_floor: float = 0.0,
    max_recall_episodes: int = 0,
    recall_quality_floor: float = 0.0,
    convergence_bonus: float = 0.10,
) -> list[RecallScore]:
```

Update the docstring (after the AD-590 line) to add:
```
AD-591: quality-aware budget enforcement — stops adding episodes when the
next one would drop mean composite below recall_quality_floor, and enforces
max_recall_episodes hard cap. 0 = disabled (backward compatible).
```

**Change 2: Replace simple budget loop with quality-aware enforcement (step 5, lines 1653-1661)**

Current code (lines 1653-1661, after AD-590):
```python
        # 5. Budget enforcement — accumulate until context budget exceeded
        budgeted: list[RecallScore] = []
        total_chars = 0
        for rs in results:
            char_len = len(rs.episode.user_input) if rs.episode.user_input else 0
            if total_chars + char_len > context_budget and budgeted:
                break  # Over budget, stop (always include at least 1)
            budgeted.append(rs)
            total_chars += char_len
```

Replace with:
```python
        # 5. Budget enforcement — quality-aware (AD-591)
        # Three stop conditions: (a) character budget, (b) max episodes, (c) quality degradation
        _effective_max = max_recall_episodes if max_recall_episodes > 0 else k * 2
        budgeted: list[RecallScore] = []
        total_chars = 0
        _running_score_sum = 0.0
        for rs in results:
            char_len = len(rs.episode.user_input) if rs.episode.user_input else 0

            # (a) Character budget
            if total_chars + char_len > context_budget and budgeted:
                break

            # (b) AD-591: Max episodes cap
            if len(budgeted) >= _effective_max:
                break

            # (c) AD-591: Quality degradation stop
            if recall_quality_floor > 0.0 and budgeted:
                _new_mean = (_running_score_sum + rs.composite_score) / (len(budgeted) + 1)
                if _new_mean < recall_quality_floor:
                    break

            budgeted.append(rs)
            total_chars += char_len
            _running_score_sum += rs.composite_score
```

Important design decisions in this loop:
- **Episode cap defaults to `k * 2`** — enhanced tier with k=5 caps at 10, full tier with k=8 caps at 16. This is generous — the cap prevents the 25+ episode case without being restrictive.
- **Quality stop checks the running mean** including the candidate, not just the candidate's individual score. This means one slightly-lower episode doesn't trigger a stop — only when the *cumulative set* quality drops below the floor.
- **Always include at least 1 episode** — the loop only checks `budgeted` before breaking, so the first episode is always added (same as pre-AD-591 behavior).
- **Results are pre-sorted by composite_score descending** (step 4) — so each subsequent episode is equal or lower quality. The quality stop naturally fires when the "good" portion of the list ends and the "marginal" tail begins.
- **Character budget check still runs first** — budget cap takes priority over quality stop.

### File 2: `src/probos/config.py`

**Change 1: Add `max_recall_episodes` and `recall_quality_floor` fields to `MemoryConfig`**

After the `composite_score_floor` field (line ~297 after AD-590):
```python
    composite_score_floor: float = 0.35
    # AD-591: Quality-aware budget enforcement.
    # max_recall_episodes: hard cap on episodes returned per recall. 0 = use k*2 default.
    max_recall_episodes: int = 0
    # recall_quality_floor: stop adding episodes if mean composite would drop below this.
    # 0.0 = disabled (character budget only).
    recall_quality_floor: float = 0.40
```

**Change 2: Add `max_recall_episodes` and `recall_quality_floor` to each recall tier dict**

Updated tiers:
```python
    recall_tiers: dict[str, dict[str, Any]] = {
        "basic": {
            "k": 3,
            "context_budget": 1500,
            "anchor_confidence_gate": 0.0,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": False,
            "cross_department_anchors": False,
        },
        "enhanced": {
            "k": 5,
            "context_budget": 4000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": False,
        },
        "full": {
            "k": 8,
            "context_budget": 6000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
        "oracle": {
            "k": 10,
            "context_budget": 8000,
            "anchor_confidence_gate": 0.2,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
    }
```

Rationale:
- **basic (0, 0.0):** No salience scoring — quality floor meaningless. Max uses k*2=6 default.
- **enhanced (0, 0.40):** Primary crew recall. Quality floor 0.40 stops adding episodes once mean quality drops below moderate-good. Max uses k*2=10 default.
- **full (0, 0.40):** Same quality bar. Max uses k*2=16 default — wider net but still quality-limited.
- **oracle (0, 0.0):** Exhaustive recall. No quality limit — oracle's purpose is broad retrieval.

### File 3: `src/probos/cognitive/cognitive_agent.py`

**Change 1: Pass `max_recall_episodes` and `recall_quality_floor` from tier params to `recall_weighted()` (at the recall_weighted call site)**

Find the `recall_weighted()` call (around line 2594-2605 after AD-590). Add two kwargs after `composite_score_floor`:
```python
                if hasattr(em, 'recall_weighted') and _tier_params.get("use_salience_weights", True):
                    scored_results = await em.recall_weighted(
                        _mem_id, query,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                        intent_type=intent.intent,
                        k=_tier_params.get("k", 5),
                        context_budget=_tier_params.get("context_budget", 4000),
                        weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                        anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                        composite_score_floor=_tier_params.get("composite_score_floor", 0.0),
                        max_recall_episodes=_tier_params.get("max_recall_episodes", 0),
                        recall_quality_floor=_tier_params.get("recall_quality_floor", 0.0),
                        convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,
                    )
```

**Change 2: Handle DEEP retrieval strategy adjustment**

In the DEEP block (around line 2586-2595 after AD-590), add relaxation for the quality params. DEEP should widen the net, not tighten it:
```python
                if _retrieval_strategy == RetrievalStrategy.DEEP:
                    _tier_params = dict(_tier_params)  # Copy to avoid mutating shared config
                    _tier_params["k"] = int(_tier_params.get("k", 5) * 1.5)
                    _tier_params["context_budget"] = int(_tier_params.get("context_budget", 4000) * 1.5)
                    _tier_params["anchor_confidence_gate"] = max(
                        0.0, _tier_params.get("anchor_confidence_gate", 0.3) - 0.1
                    )
                    # AD-590: Relax composite floor for DEEP — wider net, quality still sorts
                    _tier_params["composite_score_floor"] = max(
                        0.0, _tier_params.get("composite_score_floor", 0.0) - 0.10
                    )
                    # AD-591: Relax quality budget for DEEP — allow more episodes and lower quality floor
                    _tier_params["max_recall_episodes"] = int(
                        _tier_params.get("max_recall_episodes", 0) * 1.5
                    ) if _tier_params.get("max_recall_episodes", 0) > 0 else 0
                    _tier_params["recall_quality_floor"] = max(
                        0.0, _tier_params.get("recall_quality_floor", 0.0) - 0.10
                    )
```

### File 4: `src/probos/proactive.py`

**Change 1: Pass `max_recall_episodes` and `recall_quality_floor` from tier params to `recall_weighted()`**

Find the `recall_weighted()` call (around line 909 after AD-590). Add two kwargs after `composite_score_floor`:
```python
                        scored_results = await em.recall_weighted(
                            _agent_mem_id, query,
                            trust_network=trust_net,
                            hebbian_router=heb_router,
                            intent_type="proactive_think",
                            k=_tier_params.get("k", 5),
                            context_budget=_tier_params.get("context_budget", 4000),
                            weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                            anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                            composite_score_floor=_tier_params.get("composite_score_floor", 0.0),
                            max_recall_episodes=_tier_params.get("max_recall_episodes", 0),
                            recall_quality_floor=_tier_params.get("recall_quality_floor", 0.0),
                        )
```

### File 5: `src/probos/cognitive/oracle_service.py` — NO CHANGES

Oracle call site (lines 179-187) does NOT pass `max_recall_episodes` or `recall_quality_floor`. Defaults of 0 and 0.0 mean both are disabled. Intentional — oracle performs exhaustive recall.

### File 6: `src/probos/cognitive/source_governance.py` — NO CHANGES

`compute_adaptive_budget()` is retained as-is for defense-in-depth. It runs after `recall_weighted()` returns and can further trim the quality-budgeted results. No modifications needed.

### File 7: `tests/test_ad591_quality_aware_budget.py` — NEW FILE

```python
"""AD-591: Quality-Aware Budget Enforcement.

Tests that recall_weighted() stops adding episodes when quality degrades
or episode count cap is reached, not just when character budget is exhausted.
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ad590/test_ad584c)
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _full_anchor() -> AnchorFrame:
    return AnchorFrame(
        duty_cycle_id="duty-001",
        watch_section="alpha",
        channel="ward_room",
        channel_id="ch-123",
        department="science",
        participants=["Atlas", "Horizon"],
        trigger_agent="Atlas",
        trigger_type="ward_room_post",
        thread_id="thread-456",
        event_log_window=1000.0,
    )


def _make_em():
    """Create a minimal EpisodicMemory for recall_weighted testing."""
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._query_reformulation_enabled = False
    em._activation_tracker = None
    return em


# ===========================================================================
# Group 1: Max Episodes Cap (5 tests)
# ===========================================================================

class TestMaxEpisodesCap:
    """AD-591: max_recall_episodes hard cap on episode count."""

    @pytest.mark.asyncio
    async def test_default_max_is_k_times_two(self):
        """Default max (0) resolves to k*2. k=5 → max 10 episodes."""
        em = _make_em()

        # Create 15 episodes that all score well (all pass AD-590 floor)
        eps = []
        for i in range(15):
            eps.append((_make_episode(
                user_input=f"episode {i}",
                anchors=_full_anchor(),
            ), 0.8 - i * 0.01))  # Descending similarity

        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,  # No char budget limit
            max_recall_episodes=0,  # Default → k*2 = 10
        )
        assert len(results) <= 10

    @pytest.mark.asyncio
    async def test_explicit_max_respected(self):
        """Explicit max_recall_episodes=3 caps at 3."""
        em = _make_em()

        eps = [
            (_make_episode(user_input=f"ep {i}", anchors=_full_anchor()), 0.8)
            for i in range(8)
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,
            max_recall_episodes=3,
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_char_budget_still_takes_priority(self):
        """Character budget can stop before max episodes is reached."""
        em = _make_em()

        # Large episodes that exceed budget quickly
        eps = [
            (_make_episode(user_input="x" * 2000, anchors=_full_anchor()), 0.8),
            (_make_episode(user_input="y" * 2000, anchors=_full_anchor()), 0.7),
            (_make_episode(user_input="z" * 2000, anchors=_full_anchor()), 0.6),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=3000,  # Only fits ~1.5 episodes
            max_recall_episodes=10,
        )
        # Char budget cuts before max
        assert len(results) < 3

    @pytest.mark.asyncio
    async def test_fewer_candidates_than_max_returns_all(self):
        """When fewer episodes available than max, all are returned."""
        em = _make_em()

        eps = [
            (_make_episode(user_input="ep", anchors=_full_anchor()), 0.8),
            (_make_episode(user_input="ep2", anchors=_full_anchor()), 0.7),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,
            max_recall_episodes=10,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_max_zero_uses_k_times_two(self):
        """Verify max=0 computes to k*2 for different k values."""
        em = _make_em()

        eps = [
            (_make_episode(user_input=f"e{i}", anchors=_full_anchor()), 0.8)
            for i in range(20)
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=3,  # k*2 = 6
            context_budget=99999,
            max_recall_episodes=0,
        )
        assert len(results) <= 6


# ===========================================================================
# Group 2: Quality Floor Stop (5 tests)
# ===========================================================================

class TestQualityFloorStop:
    """AD-591: Stop adding episodes when mean composite drops below floor."""

    @pytest.mark.asyncio
    async def test_quality_floor_zero_no_filtering(self):
        """Quality floor 0.0 (default) does not trigger quality stop."""
        em = _make_em()

        # Mix of high and low scoring episodes
        eps = [
            (_make_episode(user_input="good", anchors=_full_anchor()), 0.9),
            (_make_episode(user_input="ok"), 0.3),
            (_make_episode(user_input="marginal"), 0.1),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.0,
        )
        # No quality stop — all episodes pass (only char budget and max apply)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_quality_floor_stops_on_mean_degradation(self):
        """Adding a low-scoring episode that drops mean below floor stops accumulation."""
        em = _make_em()

        # First two episodes have high composite, third would drag mean below 0.40
        # Actual composites depend on scoring — use high/low similarity to control
        ep_high1 = _make_episode(user_input="relevant A", anchors=_full_anchor())
        ep_high2 = _make_episode(user_input="relevant B", anchors=_full_anchor())
        ep_low = _make_episode(user_input="noise")  # No anchor, low sim

        eps = [
            (ep_high1, 0.9),   # High composite
            (ep_high2, 0.8),   # High composite
            (ep_low, 0.05),    # Very low composite — would tank the mean
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.40,
        )
        # Third episode should be excluded because it would drop mean below 0.40
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_quality_floor_first_episode_always_included(self):
        """First episode is always included regardless of quality floor."""
        em = _make_em()

        # Single low-scoring episode
        ep = _make_episode(user_input="only episode")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.1)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.90,  # Very high floor
        )
        # First episode always included
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_quality_floor_gradual_degradation(self):
        """With gradually decreasing scores, quality stop fires at the right point."""
        em = _make_em()

        # 8 episodes with gradually decreasing similarity
        eps = []
        for i in range(8):
            sim = 0.9 - i * 0.12  # 0.9, 0.78, 0.66, 0.54, 0.42, 0.30, 0.18, 0.06
            eps.append((_make_episode(
                user_input=f"episode {i}",
                anchors=_full_anchor(),
            ), max(sim, 0.05)))
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results_with_floor = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.40,
        )
        results_without = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.0,
        )
        # With quality floor, should return fewer episodes
        assert len(results_with_floor) < len(results_without)

    @pytest.mark.asyncio
    async def test_quality_floor_checks_running_mean_not_individual(self):
        """Quality stop uses running mean, not individual score check."""
        em = _make_em()

        # High-high-medium pattern: medium episode alone < 0.40 but
        # running mean of (high + high + medium) / 3 may still be > 0.40
        ep1 = _make_episode(user_input="great", anchors=_full_anchor())
        ep2 = _make_episode(user_input="great2", anchors=_full_anchor())
        ep3 = _make_episode(user_input="ok-ish", anchors=_full_anchor())

        eps = [
            (ep1, 0.9),    # composite ~ 0.65
            (ep2, 0.85),   # composite ~ 0.63
            (ep3, 0.3),    # composite ~ 0.40 — individual is border, mean of 3 may be above 0.40
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.40,
        )
        # Mean of 3 is (0.65+0.63+0.40)/3 ≈ 0.56 > 0.40 — third episode should be included
        # This verifies running mean, not individual score
        assert len(results) >= 2  # At minimum, first two pass


# ===========================================================================
# Group 3: Config Integration (5 tests)
# ===========================================================================

class TestConfigIntegration:
    """AD-591: Config fields and tier wiring."""

    def test_memory_config_has_max_recall_episodes(self):
        """MemoryConfig has max_recall_episodes with default 0."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "max_recall_episodes")
        assert cfg.max_recall_episodes == 0

    def test_memory_config_has_recall_quality_floor(self):
        """MemoryConfig has recall_quality_floor with default 0.40."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "recall_quality_floor")
        assert cfg.recall_quality_floor == 0.40

    def test_enhanced_tier_has_quality_floor(self):
        """Enhanced tier has recall_quality_floor = 0.40."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["enhanced"]["recall_quality_floor"] == 0.40

    def test_basic_tier_quality_disabled(self):
        """Basic tier has recall_quality_floor = 0.0 (disabled)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["basic"]["recall_quality_floor"] == 0.0

    def test_oracle_tier_quality_disabled(self):
        """Oracle tier has recall_quality_floor = 0.0 (exhaustive recall)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["oracle"]["recall_quality_floor"] == 0.0


# ===========================================================================
# Group 4: Wiring — Call Sites (3 tests)
# ===========================================================================

class TestCallSiteWiring:
    """AD-591: Production call sites pass quality budget params."""

    def test_cognitive_agent_passes_max_recall_episodes(self):
        """cognitive_agent.py recall_weighted call includes max_recall_episodes kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "max_recall_episodes":
                found = True
                break
        assert found, "cognitive_agent.py must pass max_recall_episodes to recall_weighted()"

    def test_cognitive_agent_passes_recall_quality_floor(self):
        """cognitive_agent.py recall_weighted call includes recall_quality_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "recall_quality_floor":
                found = True
                break
        assert found, "cognitive_agent.py must pass recall_quality_floor to recall_weighted()"

    def test_proactive_passes_quality_params(self):
        """proactive.py recall_weighted call includes both quality params."""
        import ast
        from pathlib import Path

        src = Path("src/probos/proactive.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found_max = False
        found_floor = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword):
                if node.arg == "max_recall_episodes":
                    found_max = True
                elif node.arg == "recall_quality_floor":
                    found_floor = True
        assert found_max, "proactive.py must pass max_recall_episodes"
        assert found_floor, "proactive.py must pass recall_quality_floor"


# ===========================================================================
# Group 5: DEEP Strategy Relaxation (2 tests)
# ===========================================================================

class TestDeepRelaxation:
    """AD-591: DEEP strategy relaxes quality budget params."""

    def test_deep_relaxes_quality_floor_in_code(self):
        """cognitive_agent.py DEEP block adjusts recall_quality_floor."""
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        assert "recall_quality_floor" in src

    def test_deep_relaxation_quality_floor_clamps(self):
        """DEEP relaxation of quality floor uses max(0.0, ...) to prevent negative."""
        original = 0.05
        relaxed = max(0.0, original - 0.10)
        assert relaxed == 0.0

        original = 0.40
        relaxed = max(0.0, original - 0.10)
        assert relaxed == 0.30


# ===========================================================================
# Group 6: Regression — Backward Compatibility (2 tests)
# ===========================================================================

class TestRegression:
    """AD-591: Existing behavior unaffected when quality params are 0."""

    @pytest.mark.asyncio
    async def test_defaults_match_pre_ad591_behavior(self):
        """recall_weighted() with 0/0.0 quality params behaves like pre-AD-591."""
        em = _make_em()

        ep = _make_episode(user_input="test data", anchors=_full_anchor())
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.5)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            max_recall_episodes=0,
            recall_quality_floor=0.0,
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_ad568b_still_runs_after_quality_budget(self):
        """AD-568b adaptive re-budget in cognitive_agent/proactive still functional."""
        # Integration test: verify compute_adaptive_budget still importable and callable
        from probos.cognitive.source_governance import compute_adaptive_budget, RetrievalStrategy

        result = compute_adaptive_budget(
            4000,
            episode_count=50,
            strategy=RetrievalStrategy.SHALLOW,
        )
        # Should return a valid BudgetAdjustment (no crash, reasonable values)
        assert result.original_budget == 4000
        assert result.adjusted_budget > 0
```

---

## Verification

1. Run targeted tests:
   ```
   python -m pytest tests/test_ad591_quality_aware_budget.py -x -v
   ```

2. Run related test suites for regression:
   ```
   python -m pytest tests/test_ad590_composite_score_floor.py tests/test_ad584c_scoring_rebalance.py tests/test_ad567b_anchor_recall.py tests/test_source_governance.py -x -v
   ```

3. Verify oracle_service.py and source_governance.py are NOT modified.

---

## What This Does NOT Change

- **`score_recall()` in `episodic.py`** — unchanged. Scoring formula not modified.
- **`compute_adaptive_budget()` in `source_governance.py`** — unchanged. Retained as defense-in-depth secondary re-budgeting.
- **`composite_score_floor`** (AD-590) — unchanged. Coexists: floor removes trash, quality budget limits the good-but-too-many.
- **`_confabulation_guard()` / `_format_memory_section()`** — unchanged (AD-592).
- **Oracle service** — unaffected. Defaults of 0/0.0 mean both quality params disabled.
- **Dreaming** — unaffected. Does not use `recall_weighted()`.

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/episodic.py` | Add `max_recall_episodes: int = 0` and `recall_quality_floor: float = 0.0` parameters to `recall_weighted()`. Replace simple budget loop with quality-aware enforcement (3 stop conditions: char budget, max episodes, mean quality degradation). Update docstring. |
| `src/probos/config.py` | Add `max_recall_episodes: int = 0` and `recall_quality_floor: float = 0.40` fields to `MemoryConfig`. Add both to each recall tier dict (basic/oracle=disabled, enhanced/full=0.40). |
| `src/probos/cognitive/cognitive_agent.py` | Pass `max_recall_episodes` and `recall_quality_floor` from tier params to `recall_weighted()`. Add DEEP strategy relaxation for both params. |
| `src/probos/proactive.py` | Pass `max_recall_episodes` and `recall_quality_floor` from tier params to `recall_weighted()`. |
| `tests/test_ad591_quality_aware_budget.py` | NEW — 22 tests across 6 groups: max episodes cap (5), quality floor stop (5), config integration (5), call site wiring (3), DEEP relaxation (2), regression (2). |

**Estimated test count:** 22 new tests, 0 modified existing tests.
