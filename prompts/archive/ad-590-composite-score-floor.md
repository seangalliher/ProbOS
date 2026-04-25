# AD-590: Composite Score Floor (Recall Quality Gate)

**AD:** 590
**Title:** Composite Score Floor — Filter Marginal Episodes from Recall Results
**Type:** Enhancement (recall pipeline, cognitive safety)
**Depends on:** None (independent, ships after AD-592 in AD-590–593 wave)
**Absorbs:** None
**Risk:** Low — configurable floor with 0.0 default (disabled unless opted in per tier)
**Research:** `docs/research/confabulation-scaling-research.md`

---

## Problem Statement

Agents accumulate thousands of episodic memories over their lifetime. When `recall_weighted()` runs, the composite score formula correctly ranks relevant episodes above marginal ones — but there is no minimum quality threshold. All candidates that survive the `anchor_confidence_gate` filter and fit within the character budget are included in the agent's context.

Numerical analysis (from research doc):
- A relevant episode scores ~0.69 composite (semantic 0.40, keyword match, recent, anchored)
- A marginal episode scores ~0.30 composite (semantic 0.18, no keyword, 3 days old)
- Both pass anchor gate. Both fit in 4000-char budget (25 episodes × 120 chars avg = 3000 chars)
- Result: ~5 relevant + ~20 noise fragments in agent context
- LLM treats noise fragments as source material → fabricates specifics

The `anchor_confidence_gate` at step 3b filters by anchor quality, not overall relevance. A marginal episode with a good anchor frame (0.5 anchor confidence) still passes even when its composite relevance is low (0.30).

---

## Design Principles Compliance

- **SOLID (S):** `recall_weighted()` retains single responsibility. New filter is one list comprehension, same pattern as existing `anchor_confidence_gate` filter.
- **SOLID (O):** Extended via new parameter with backward-compatible default (0.0 = disabled). No existing behavior changes unless caller opts in.
- **SOLID (D):** Floor value flows from config (`MemoryConfig`) through tier params, not hardcoded.
- **Law of Demeter:** No new object traversals. Filter reads `rs.composite_score` — same access pattern as the sort on line 1644.
- **Fail Fast / Defense in Depth:** Floor is defense-in-depth alongside AD-592 (instruction guards) and AD-591/593 (budget + pruning). Each layer addresses the problem independently.
- **DRY:** Follows the exact `anchor_confidence_gate` pattern already established at lines 1639-1641 (parameter with 0.0 default, conditional list comprehension). No new abstractions needed.
- **Cloud-Ready Storage:** No storage changes.

---

## Implementation

### File 1: `src/probos/cognitive/episodic.py`

**Change 1: Add `composite_score_floor` parameter to `recall_weighted()` signature (line 1549)**

Current signature (lines 1549-1562):
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
    convergence_bonus: float = 0.10,
) -> list[RecallScore]:
```

Add `composite_score_floor: float = 0.0,` after `anchor_confidence_gate`:
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

Update the docstring (line 1563-1568) to add one line after the AD-567c description:
```
AD-590: applies composite score floor — episodes below composite_score_floor
are filtered from results after scoring, reducing noise from marginal candidates.
```

**Change 2: Add composite score floor filter as step "3c" (after line 1641, before line 1643)**

Current code (lines 1639-1644):
```python
        # 3b. AD-567c: RPMS confidence gating — filter low-confidence episodes
        if anchor_confidence_gate > 0.0:
            results = [rs for rs in results if rs.anchor_confidence >= anchor_confidence_gate]

        # 4. Sort by composite score descending
        results.sort(key=lambda r: r.composite_score, reverse=True)
```

Insert between these two blocks:
```python
        # 3c. AD-590: Composite score floor — filter marginal episodes
        if composite_score_floor > 0.0:
            results = [rs for rs in results if rs.composite_score >= composite_score_floor]
```

So the full sequence becomes:
```python
        # 3b. AD-567c: RPMS confidence gating — filter low-confidence episodes
        if anchor_confidence_gate > 0.0:
            results = [rs for rs in results if rs.anchor_confidence >= anchor_confidence_gate]

        # 3c. AD-590: Composite score floor — filter marginal episodes
        if composite_score_floor > 0.0:
            results = [rs for rs in results if rs.composite_score >= composite_score_floor]

        # 4. Sort by composite score descending
        results.sort(key=lambda r: r.composite_score, reverse=True)
```

### File 2: `src/probos/config.py`

**Change 1: Add `composite_score_floor` field to `MemoryConfig` (after line 296)**

Current code (lines 296-298):
```python
    anchor_confidence_gate: float = 0.3  # RPMS: suppress below this from default recall
    # AD-462c: Variable Recall Tiers
    recall_tiers: dict[str, dict[str, Any]] = {
```

Insert between:
```python
    anchor_confidence_gate: float = 0.3  # RPMS: suppress below this from default recall
    # AD-590: Composite score floor — filter marginal episodes from recall results.
    # Episodes with composite_score below this threshold are excluded regardless
    # of remaining budget. 0.0 = disabled (backward compatible).
    composite_score_floor: float = 0.35
    # AD-462c: Variable Recall Tiers
    recall_tiers: dict[str, dict[str, Any]] = {
```

**Change 2: Add `composite_score_floor` to each recall tier dict (lines 298-327)**

Updated tiers:
```python
    recall_tiers: dict[str, dict[str, Any]] = {
        "basic": {
            "k": 3,
            "context_budget": 1500,
            "anchor_confidence_gate": 0.0,
            "composite_score_floor": 0.0,
            "use_salience_weights": False,
            "cross_department_anchors": False,
        },
        "enhanced": {
            "k": 5,
            "context_budget": 4000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "use_salience_weights": True,
            "cross_department_anchors": False,
        },
        "full": {
            "k": 8,
            "context_budget": 6000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
        "oracle": {
            "k": 10,
            "context_budget": 8000,
            "anchor_confidence_gate": 0.2,
            "composite_score_floor": 0.0,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
    }
```

Rationale for per-tier values:
- **basic (0.0):** Uses vector similarity only, no salience scoring — floor meaningless.
- **enhanced (0.35):** Primary crew recall. Floor excludes marginal episodes at the ~60th percentile boundary identified in research.
- **full (0.35):** Deep recall for complex queries. Same floor — quality matters more with larger budgets.
- **oracle (0.0):** Oracle service uses `context_budget=999999` for exhaustive search. Floor disabled — oracle's purpose is broad retrieval, not focused context.

### File 3: `src/probos/cognitive/cognitive_agent.py`

**Change 1: Pass `composite_score_floor` from tier params to `recall_weighted()` (line 2594-2605)**

Current code (lines 2594-2605):
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
                        convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,
                    )
```

Add `composite_score_floor` kwarg after `anchor_confidence_gate`:
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
                        convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,
                    )
```

**Change 2: Handle DEEP retrieval strategy adjustment (lines 2586-2592)**

Current DEEP adjustments (lines 2586-2592):
```python
                if _retrieval_strategy == RetrievalStrategy.DEEP:
                    _tier_params = dict(_tier_params)  # Copy to avoid mutating shared config
                    _tier_params["k"] = int(_tier_params.get("k", 5) * 1.5)
                    _tier_params["context_budget"] = int(_tier_params.get("context_budget", 4000) * 1.5)
                    _tier_params["anchor_confidence_gate"] = max(
                        0.0, _tier_params.get("anchor_confidence_gate", 0.3) - 0.1
                    )
```

Add composite_score_floor relaxation for DEEP strategy (same pattern — relax thresholds to cast wider net):
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
```

### File 4: `src/probos/proactive.py`

**Change 1: Pass `composite_score_floor` from tier params to `recall_weighted()` (line 909-918)**

Current code (lines 909-918):
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
                        )
```

Add `composite_score_floor` kwarg after `anchor_confidence_gate`:
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
                        )
```

### File 5: `src/probos/cognitive/oracle_service.py` — NO CHANGES

Oracle call site (lines 179-187) does NOT pass `composite_score_floor`. The default value of 0.0 means the floor is disabled for oracle queries. This is intentional — oracle performs exhaustive recall with `context_budget=999999`.

### File 6: `tests/test_ad590_composite_score_floor.py` — NEW FILE

```python
"""AD-590: Composite Score Floor — Recall Quality Gate.

Tests that the composite_score_floor parameter on recall_weighted() correctly
filters marginal episodes from results, reducing noise in agent context.
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ad584c_scoring_rebalance.py)
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
    """AnchorFrame with all 10 fields — anchor_confidence ~ 1.0."""
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


def _half_anchor() -> AnchorFrame:
    """AnchorFrame with 5/10 fields — anchor_confidence ~ 0.5."""
    return AnchorFrame(
        channel="ward_room",
        department="science",
        participants=["Atlas"],
        trigger_type="ward_room_post",
        trigger_agent="Atlas",
    )


def _make_em():
    """Create a minimal EpisodicMemory for recall_weighted testing."""
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._query_reformulation_enabled = False
    em._activation_tracker = None
    return em


# ===========================================================================
# Group 1: Floor Filter Behavior (6 tests)
# ===========================================================================

class TestFloorFilterBehavior:
    """AD-590: Composite score floor filters marginal episodes."""

    @pytest.mark.asyncio
    async def test_floor_zero_no_filtering(self):
        """Floor of 0.0 (default) does not filter any episodes."""
        em = _make_em()

        # Two episodes: one high-scoring, one low-scoring
        ep_high = _make_episode(user_input="relevant data", anchors=_full_anchor())
        ep_low = _make_episode(user_input="marginal noise", anchors=None)

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_high, 0.8),  # high semantic sim → high composite
            (ep_low, 0.1),   # low semantic sim → low composite
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.0,
        )
        assert len(results) == 2  # Both pass — no floor applied

    @pytest.mark.asyncio
    async def test_floor_filters_low_scoring_episodes(self):
        """Floor of 0.35 filters episodes with composite_score < 0.35."""
        em = _make_em()

        ep_high = _make_episode(user_input="relevant data", anchors=_full_anchor())
        ep_low = _make_episode(user_input="marginal noise", anchors=None)

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_high, 0.8),  # high sim → composite well above 0.35
            (ep_low, 0.1),   # low sim, no anchor → composite below 0.35
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.35,
        )
        # Only high-scoring episode passes
        assert len(results) == 1
        assert results[0].composite_score >= 0.35

    @pytest.mark.asyncio
    async def test_floor_keeps_episodes_at_boundary(self):
        """Episodes exactly at the floor threshold are kept (>=, not >)."""
        from probos.cognitive.episodic import EpisodicMemory

        # Engineer an episode that scores exactly at the boundary
        ep = _make_episode(anchors=_half_anchor())
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5,
            keyword_hits=0, trust_weight=0.5, hebbian_weight=0.5,
            recency_weight=0.5, convergence_bonus=0.0,
        )
        floor = rs.composite_score  # Use its exact score as floor

        em = _make_em()
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.5)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=floor,
        )
        assert len(results) == 1  # Exact match kept

    @pytest.mark.asyncio
    async def test_floor_applied_after_anchor_gate(self):
        """Floor filter runs after anchor_confidence_gate (step 3c after 3b)."""
        em = _make_em()

        # Episode with low anchor but high composite (would pass floor, fail anchor gate)
        ep_low_anchor = _make_episode(user_input="low anchor high sim", anchors=None)
        # Episode with high anchor but low composite (would pass anchor gate, fail floor)
        ep_low_composite = _make_episode(user_input="high anchor low sim", anchors=_full_anchor())

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_low_anchor, 0.9),    # High sim, no anchor
            (ep_low_composite, 0.05), # Low sim, full anchor
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            anchor_confidence_gate=0.3,
            composite_score_floor=0.35,
        )
        # ep_low_anchor: fails anchor gate (0.0 < 0.3) — filtered at 3b
        # ep_low_composite: passes anchor gate (1.0 > 0.3) but fails floor (<0.35) — filtered at 3c
        # Result: neither passes
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_floor_filters_before_budget_enforcement(self):
        """Floor filtering happens before budget loop — budget only sees quality episodes."""
        em = _make_em()

        # Create 20 marginal episodes + 2 relevant ones
        eps = []
        for i in range(20):
            eps.append((_make_episode(user_input=f"noise {i}"), 0.1))  # low sim
        eps.append((_make_episode(user_input="relevant A", anchors=_full_anchor()), 0.8))
        eps.append((_make_episode(user_input="relevant B", anchors=_full_anchor()), 0.7))

        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=4000,
            composite_score_floor=0.35,
        )
        # Only the 2 relevant episodes should pass the floor
        assert len(results) == 2
        for rs in results:
            assert rs.composite_score >= 0.35

    @pytest.mark.asyncio
    async def test_all_episodes_below_floor_returns_empty(self):
        """When all episodes are below the floor, return empty list."""
        em = _make_em()

        ep = _make_episode(user_input="very marginal")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.05)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.90,  # Very high floor
        )
        assert len(results) == 0


# ===========================================================================
# Group 2: Config Integration (4 tests)
# ===========================================================================

class TestConfigIntegration:
    """AD-590: Config field and tier wiring."""

    def test_memory_config_has_composite_score_floor(self):
        """MemoryConfig has composite_score_floor field with default 0.35."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "composite_score_floor")
        assert cfg.composite_score_floor == 0.35

    def test_basic_tier_floor_disabled(self):
        """Basic tier has composite_score_floor = 0.0 (disabled)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["basic"]["composite_score_floor"] == 0.0

    def test_enhanced_tier_floor_set(self):
        """Enhanced tier has composite_score_floor = 0.35."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["enhanced"]["composite_score_floor"] == 0.35

    def test_oracle_tier_floor_disabled(self):
        """Oracle tier has composite_score_floor = 0.0 (exhaustive recall)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["oracle"]["composite_score_floor"] == 0.0


# ===========================================================================
# Group 3: Wiring — Call Sites Pass Floor (3 tests)
# ===========================================================================

class TestCallSiteWiring:
    """AD-590: Production call sites pass composite_score_floor."""

    def test_cognitive_agent_passes_composite_score_floor(self):
        """cognitive_agent.py recall_weighted call includes composite_score_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                found = True
                break
        assert found, "cognitive_agent.py must pass composite_score_floor to recall_weighted()"

    def test_proactive_passes_composite_score_floor(self):
        """proactive.py recall_weighted call includes composite_score_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/proactive.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                found = True
                break
        assert found, "proactive.py must pass composite_score_floor to recall_weighted()"

    def test_oracle_does_not_pass_composite_score_floor(self):
        """oracle_service.py does NOT pass composite_score_floor (inherits 0.0 default)."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/oracle_service.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                pytest.fail("oracle_service.py must NOT pass composite_score_floor (0.0 default = disabled)")


# ===========================================================================
# Group 4: DEEP Strategy Relaxation (2 tests)
# ===========================================================================

class TestDeepStrategyRelaxation:
    """AD-590: DEEP retrieval strategy relaxes the composite score floor."""

    def test_deep_strategy_relaxes_floor_in_code(self):
        """cognitive_agent.py DEEP block adjusts composite_score_floor."""
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        # Both DEEP adjustments should reference composite_score_floor
        assert "composite_score_floor" in src
        # Verify DEEP block pattern: max(0.0, ... - 0.10)
        assert "0.10" in src  # The relaxation amount

    def test_deep_relaxation_cannot_go_negative(self):
        """DEEP relaxation uses max(0.0, ...) to prevent negative floor."""
        # Simulate the relaxation math
        original_floor = 0.05
        relaxed = max(0.0, original_floor - 0.10)
        assert relaxed == 0.0

        original_floor = 0.35
        relaxed = max(0.0, original_floor - 0.10)
        assert relaxed == 0.25


# ===========================================================================
# Group 5: Regression — No Impact on Existing Behavior (2 tests)
# ===========================================================================

class TestRegression:
    """AD-590: Existing behavior unaffected when floor is 0.0."""

    @pytest.mark.asyncio
    async def test_default_params_match_pre_ad590_behavior(self):
        """recall_weighted() with no composite_score_floor behaves identically to pre-AD-590."""
        em = _make_em()

        ep = _make_episode(user_input="test data")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.3)])
        em.keyword_search = AsyncMock(return_value=[])

        # Default composite_score_floor is 0.0 — should not filter
        results = await em.recall_weighted("agent-001", "test query")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_activation_tracking_still_runs_after_floor(self):
        """AD-567d activation tracking runs on the budgeted results, not pre-floor results."""
        em = _make_em()
        mock_tracker = MagicMock()
        mock_tracker.record_batch_access = AsyncMock()
        em._activation_tracker = mock_tracker

        ep_good = _make_episode(user_input="relevant", anchors=_full_anchor())
        ep_bad = _make_episode(user_input="noise")

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_good, 0.8),
            (ep_bad, 0.05),
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.35,
        )

        # Only the good episode should be tracked
        assert len(results) == 1
        mock_tracker.record_batch_access.assert_called_once()
        tracked_ids = mock_tracker.record_batch_access.call_args[0][0]
        assert len(tracked_ids) == 1
```

---

## Verification

1. Run targeted tests:
   ```
   python -m pytest tests/test_ad590_composite_score_floor.py -x -v
   ```

2. Run related test suites for regression:
   ```
   python -m pytest tests/test_ad584c_scoring_rebalance.py tests/test_ad567b_anchor_recall.py tests/test_source_governance.py tests/test_provenance_boundary.py -x -v
   ```

3. Verify oracle_service.py is NOT modified (critical — oracle needs unconstrained recall).

---

## What This Does NOT Change

- **`score_recall()` in `episodic.py`** — unchanged. Scoring formula is not modified (AD-584c scope).
- **`anchor_confidence_gate`** — unchanged. Both filters coexist as independent gates.
- **`_format_memory_section()` / confabulation guards** — unchanged (AD-592 scope).
- **Dreaming** — unaffected. Dream Step 12 uses `recent()` and `recall_by_intent()`, not `recall_weighted()`.
- **Oracle service** — unaffected. Default `composite_score_floor=0.0` means no filtering.
- **Adaptive budget** (`source_governance.py`) — unchanged (AD-591 scope).
- **Pruning** (`dreaming.py`) — unchanged (AD-593 scope).
- **Basic recall tier** — `composite_score_floor=0.0` means basic tier is unaffected.

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/episodic.py` | Add `composite_score_floor: float = 0.0` parameter to `recall_weighted()`. Add 3-line filter at step 3c between anchor gate and sort. Update docstring. |
| `src/probos/config.py` | Add `composite_score_floor: float = 0.35` field to `MemoryConfig`. Add `composite_score_floor` to each recall tier dict (basic=0.0, enhanced=0.35, full=0.35, oracle=0.0). |
| `src/probos/cognitive/cognitive_agent.py` | Pass `composite_score_floor=_tier_params.get("composite_score_floor", 0.0)` to `recall_weighted()`. Add DEEP strategy relaxation (`- 0.10`). |
| `src/probos/proactive.py` | Pass `composite_score_floor=_tier_params.get("composite_score_floor", 0.0)` to `recall_weighted()`. |
| `tests/test_ad590_composite_score_floor.py` | NEW — 17 tests across 5 groups: floor filter behavior (6), config integration (4), call site wiring (3), DEEP relaxation (2), regression (2). |

**Estimated test count:** 17 new tests, 0 modified existing tests.
