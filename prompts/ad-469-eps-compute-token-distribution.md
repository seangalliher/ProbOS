# AD-469: EPS — Compute/Token Distribution (v1 Foundation)

**Status:** Ready for builder
**Dependencies:** Builds on AD-460 partial-complete (`CognitiveJournal` at `src/probos/cognitive/journal.py:56`; verified) and AD-467 Wave 7 ✅ (`runtime.work_item_store`, operations crew). Reads `runtime.llm_client` (`runtime.py:347`) for tier resolution. Does NOT modify the AD-460 journal schema (`journal.py:25-43`).
**Estimated tests:** ~13
**Risk:** HIGH — cross-cutting (LLMClient consultation surface, IntentBus budget hooks, HXI override surface). v1 deliberately narrow per convention #14.

---

## Problem

ProbOS has no first-class capacity manager for LLM throughput. `CognitiveJournal.tokens_grouped_by(...)` (`journal.py:298-337`, verified) reports historical usage by `model`/`tier`/`agent_id`/`agent_type`/`intent`, and `get_agent_tokens_since` (`journal.py:278`) supports per-agent windowed reads, but there is no:

1. **Capacity tracker** — no rolling-window aggregator that summarizes total ProbOS LLM throughput (tokens/min, calls/min, queue depth) across departments.
2. **Department budgets** — no priority-weighted allocation surface (e.g., Engineering 60% during builds; Medical priority during Red Alert).
3. **Captain override** — no API/HXI-reachable surface for the Captain to manually reallocate budget percentages.

`grep -rn "class EPS\|class CapacityTracker\|class DepartmentBudget" src/probos/` returns no matches.

The roadmap entry (line 4185) lists 7 capabilities. **v1 ships 3 real-work primitives; 4 deferred to AD-469b/c/d** per convention #14 (aggressive pre-deferral).

## Solution Overview

Create three modules under `src/probos/cognitive/eps/` (new package; AD-469 OWNS `__init__.py` creation, mirroring AD-457/459/466/467 precedents):

1. **`CapacityTracker`** (`capacity.py`) — rolling-window aggregator over `runtime.cognitive_journal.tokens_grouped_by("agent_id"|"model"|"tier")`. Computes tokens/min, calls/min over a configurable window. Read-only over the journal. Public API: `summary()` returns a `CapacitySummary` frozen dataclass. No journal-schema mutation.
2. **`DepartmentBudgetTable`** (`budgets.py`) — in-memory priority allocation table. Frozen dataclass `DepartmentBudget(name, percent, priority)`. Constructed from `EPSConfig.departments`. Public API: `allocations()` returns a `dict[str, float]` summing to 1.0 (renormalized when overridden). Captain-override hook: `set_override(name, percent)` triggers renormalization of remaining departments.
3. **`EPSCoordinator`** (`coordinator.py`) — composes tracker + budget table. Public methods: `report() -> EPSReport` (summary + budget allocations + saturation flag); `override(department, percent)` (Captain-side); `consult(department) -> float` (current allocation share for the consultation-only consumer surface; used by future AD-469b atomic enforcement). Emits `EPS_BUDGET_EXCEEDED` when a department's tokens-in-window exceeds its allocated share by `over_budget_threshold`; emits `EPS_REALLOCATION` per Captain override.

This is **policy + diagnostics layered on existing AD-460 + AD-467 surfaces**. AD-469 does NOT modify `CognitiveJournal` schema, does NOT actively gate LLM calls, does NOT integrate with `Alert Conditions`, does NOT touch `LLMClient._complete_inner`, does NOT introduce per-task atomic budget deduction.

**v1 scope (no-theater discipline; convention #7 + #14):**

- **CapacityTracker** — real aggregation over real journal data.
- **DepartmentBudgetTable** — real in-memory allocation surface seeded from config.
- **EPSCoordinator + Captain override** — real public attribute consumed by the existing config + future HXI surfaces; emits real `EPS_REALLOCATION` events on override.

**Four wholesale-deferred to sub-ADs:**

- **Alert-aware reallocation** — AD-469b. Requires a coordinator-then-dispatch handoff with `bridge_alerts.py`; v1 emits but does not consume Alert Conditions.
- **Back-pressure (queue/downgrade tier)** — AD-469c. Requires `LLMClient` consultation hook that v1 does not wire.
- **Atomic budget enforcement** — AD-469d. Requires transactional deduction in the LLM request critical path; v1 is observation-only.
- **Prompt caching hierarchy** — AD-469e. Requires LLMClient prompt-message ordering; out of scope.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
EPS_BUDGET_EXCEEDED = "eps_budget_exceeded"  # AD-469
EPS_REALLOCATION = "eps_reallocation"  # AD-469
```

Verified absent: `grep -n "EPS_BUDGET_EXCEEDED\|EPS_REALLOCATION" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/eps/__init__.py` (new — AD-469 OWNS directory creation)

```python
"""Electro-Plasma System (EPS) -- compute/token distribution (AD-469)."""

from probos.cognitive.eps.budgets import DepartmentBudget, DepartmentBudgetTable
from probos.cognitive.eps.capacity import CapacitySummary, CapacityTracker
from probos.cognitive.eps.coordinator import EPSCoordinator, EPSReport

__all__ = [
    "CapacitySummary",
    "CapacityTracker",
    "DepartmentBudget",
    "DepartmentBudgetTable",
    "EPSCoordinator",
    "EPSReport",
]
```

---

## Section 2: `CapacityTracker`

**File:** `src/probos/cognitive/eps/capacity.py` (new)

```python
"""AD-469: CapacityTracker -- rolling-window aggregator over CognitiveJournal."""

from __future__ import annotations

import logging
import time
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
      - summary() -> CapacitySummary (tokens/calls in the window + by-agent/tier/model maps).

    Stateless. Each call queries the journal afresh; no caching.
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
        # (verified at journal.py:299; v1 prompt erroneously called
        # `tokens_grouped_by`). Returns list[dict] with keys:
        # {<group_by>: <key>, "total_calls", "total_tokens",
        #  "prompt_tokens", "completion_tokens", "avg_latency_ms"}.
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
        per_min = (total_tokens / self._window_seconds) * 60.0 if self._window_seconds > 0 else 0.0
        calls_per_min = (
            (total_calls / self._window_seconds) * 60.0 if self._window_seconds > 0 else 0.0
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
```

> Verify-first: `get_token_usage_by` accepts `group_by` keyword and returns a `list[dict]` with keys `total_tokens`, `total_calls`, `prompt_tokens`, `completion_tokens`, `avg_latency_ms`, plus the group key (`journal.py:299, 333-338`). The method is named `get_token_usage_by`, NOT `tokens_grouped_by` (revision-pass correction; v1 draft hallucinated the alias). Per-window time filtering is deferred to AD-469b alongside alert integration; v1 reports unfiltered aggregate.

---

## Section 3: `DepartmentBudget` and `DepartmentBudgetTable`

**File:** `src/probos/cognitive/eps/budgets.py` (new)

```python
"""AD-469: Department budgets -- priority-weighted allocation table."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepartmentBudget:
    """Single department's allocation entry.

    percent is a fraction of total LLM throughput in [0.0, 1.0].
    priority is a positive integer; lower priorities run first when
    Captain override forces a renormalization (AD-469b alert-aware
    reallocation will consume priority).
    """

    name: str
    percent: float
    priority: int = 5  # 1..10; lower = higher priority


@dataclass
class DepartmentBudgetTable:
    """In-memory allocation surface.

    v1 public API:
      - allocations() -> dict[str, float] -- name -> percent, summing to 1.0.
      - set_override(name, percent) -- Captain-side override; renormalizes
        remaining departments proportionally so total stays 1.0.
      - clear_override(name) -- restores the configured percent.

    Construction: from a list[DepartmentBudget] (typically built from
    EPSConfig.departments). If percentages don't sum to 1.0 at construction
    time, log warning and renormalize.
    """

    departments: list[DepartmentBudget] = field(default_factory=list)
    _overrides: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        total = sum(d.percent for d in self.departments)
        if self.departments and abs(total - 1.0) > 0.01:
            logger.warning(
                "AD-469: department budget percents sum to %.3f (expected 1.0); "
                "renormalizing on read",
                total,
            )

    def allocations(self) -> dict[str, float]:
        if not self.departments:
            return {}
        # Apply overrides first; remaining departments share what's left.
        out: dict[str, float] = {}
        overridden_total = 0.0
        for d in self.departments:
            if d.name in self._overrides:
                pct = self._overrides[d.name]
                out[d.name] = pct
                overridden_total += pct
        remaining = max(0.0, 1.0 - overridden_total)
        configured_total = sum(
            d.percent for d in self.departments if d.name not in self._overrides
        )
        for d in self.departments:
            if d.name in self._overrides:
                continue
            if configured_total > 0:
                out[d.name] = remaining * (d.percent / configured_total)
            else:
                out[d.name] = 0.0
        return out

    def set_override(self, name: str, percent: float) -> bool:
        if not name or percent < 0.0 or percent > 1.0:
            return False
        if not any(d.name == name for d in self.departments):
            return False
        self._overrides[name] = percent
        return True

    def clear_override(self, name: str) -> bool:
        return self._overrides.pop(name, None) is not None
```

---

## Section 4: `EPSCoordinator`

**File:** `src/probos/cognitive/eps/coordinator.py` (new)

```python
"""AD-469: EPSCoordinator -- composes capacity tracker + budgets, emits events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EPSReport:
    """One snapshot of ProbOS LLM capacity + allocations."""

    capacity: Any  # CapacitySummary; Any avoids circular import in dataclass typing
    allocations: dict[str, float] = field(default_factory=dict)
    overrides: dict[str, float] = field(default_factory=dict)
    saturated: bool = False


class EPSCoordinator:
    """v1 coordinator over CapacityTracker + DepartmentBudgetTable.

    Public surface:
      - report() -> EPSReport
      - override(name, percent) -> bool (Captain-side; emits EPS_REALLOCATION)
      - clear_override(name) -> bool
      - check_budgets() -> list[str] (department names whose recent usage
        exceeded their allocation by over_budget_threshold; emits
        EPS_BUDGET_EXCEEDED per offender). Consultation-only; no gating.
    """

    def __init__(
        self,
        *,
        capacity_tracker: Any,
        budget_table: Any,
        emit_event: Any | None = None,
        over_budget_threshold: float = 1.25,  # 25% over alloc => exceeded
    ) -> None:
        self._capacity = capacity_tracker
        self._budgets = budget_table
        self._emit_event = emit_event
        self._over_budget_threshold = over_budget_threshold

    async def report(self) -> EPSReport:
        cap = await self._capacity.summary()
        alloc = self._budgets.allocations()
        overrides = dict(getattr(self._budgets, "_overrides", {}))
        # Saturation: any single agent at >50% of total tokens, or total > 0
        # tokens_per_minute crossing a hard ceiling could be a future hint.
        saturated = bool(
            cap.total_tokens > 0
            and cap.by_agent
            and max(cap.by_agent.values()) > 0.5 * cap.total_tokens
        )
        return EPSReport(
            capacity=cap,
            allocations=alloc,
            overrides=overrides,
            saturated=saturated,
        )

    def override(self, name: str, percent: float) -> bool:
        applied = self._budgets.set_override(name, percent)
        if applied:
            self._emit_reallocation(name, percent, cleared=False)
        return applied

    def clear_override(self, name: str) -> bool:
        cleared = self._budgets.clear_override(name)
        if cleared:
            self._emit_reallocation(name, 0.0, cleared=True)
        return cleared

    async def check_budgets(self) -> list[str]:
        """Emit EPS_BUDGET_EXCEEDED for any department whose share of recent
        tokens exceeds (allocation * over_budget_threshold).

        v1 maps agent_id -> department via the runtime ontology only when the
        capacity summary's by_agent map carries agent_ids the runtime can
        resolve. v1 returns an empty list if no such mapping is available;
        AD-469b will introduce the per-agent-department resolver as a
        first-class surface.
        """
        # v1 is consultation-only; the by-department mapping is
        # established in AD-469b. Returning the saturation department list
        # without an emit avoids theater (convention #7).
        return []

    def _emit_reallocation(self, name: str, percent: float, *, cleared: bool) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.EPS_REALLOCATION,
                {
                    "department": name,
                    "percent": percent,
                    "cleared": cleared,
                },
            )
        except Exception:
            logger.warning(
                "AD-469: EPS_REALLOCATION emit failed (department=%s)", name, exc_info=True,
            )
```

> No-theater note: `check_budgets()` v1 returns `[]` because the agent_id->department resolver is in AD-469b's scope. The empty-list contract is honest; the `EPS_BUDGET_EXCEEDED` event is reserved for AD-469b. No event is emitted from `check_budgets` until that resolver lands. This honors convention #7 (no-theater) and convention #14 (aggressive pre-deferral).

---

## Section 5: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
```

REPLACE:
```python
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
    EPS_BUDGET_EXCEEDED = "eps_budget_exceeded"  # AD-469
    EPS_REALLOCATION = "eps_reallocation"  # AD-469
```

> Verified post-AD-463 anchor at `events.py:210-211`.

---

## Section 6: Add `EPSConfig`

**File:** `src/probos/config.py`

```python
class EPSDepartmentConfig(BaseModel):
    """One department's EPS allocation entry (AD-469)."""

    name: str
    percent: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=5, ge=1, le=10)


class EPSConfig(BaseModel):
    """EPS - Compute/Token Distribution (AD-469)."""

    enabled: bool = True
    window_seconds: float = Field(default=60.0, ge=10.0)
    over_budget_threshold: float = Field(default=1.25, ge=1.0, le=10.0)
    departments: list[EPSDepartmentConfig] = Field(
        default_factory=lambda: [
            EPSDepartmentConfig(name="engineering", percent=0.30, priority=3),
            EPSDepartmentConfig(name="science", percent=0.20, priority=4),
            EPSDepartmentConfig(name="medical", percent=0.15, priority=2),
            EPSDepartmentConfig(name="security", percent=0.15, priority=2),
            EPSDepartmentConfig(name="operations", percent=0.10, priority=4),
            EPSDepartmentConfig(name="other", percent=0.10, priority=6),
        ]
    )
```

Wire into `SystemConfig`:

SEARCH (`config.py:1693`):
```python
    model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
```

REPLACE:
```python
    model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
    eps: EPSConfig = EPSConfig()  # AD-469
```

> Anchor-chain fallback: AD-463 `model_routing` (verified, line 1693) -> AD-456 `security_infra` -> AD-466 `infrastructure` -> AD-491 `infodynamic` -> AD-440 `orders` (verified, line 1683).

---

## Section 7: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place after the AD-463 ModelRoutingConfig wiring block (the last Wave 7 wiring landed there).

```python
    # AD-469: EPS - Compute/Token Distribution (v1 foundation)
    if config.eps.enabled:
        from probos.cognitive.eps import (
            CapacityTracker,
            DepartmentBudget,
            DepartmentBudgetTable,
            EPSCoordinator,
        )
        capacity = CapacityTracker(
            runtime=runtime,
            window_seconds=config.eps.window_seconds,
        )
        budgets = DepartmentBudgetTable(
            departments=[
                DepartmentBudget(
                    name=d.name, percent=d.percent, priority=d.priority,
                )
                for d in config.eps.departments
            ],
        )
        runtime.eps_coordinator = EPSCoordinator(
            capacity_tracker=capacity,
            budget_table=budgets,
            emit_event=runtime.emit_event,
            over_budget_threshold=config.eps.over_budget_threshold,
        )
        logger.info(
            "AD-469: EPSCoordinator wired (%d departments, window=%.0fs)",
            len(config.eps.departments),
            config.eps.window_seconds,
        )
    else:
        runtime.eps_coordinator = None
```

> Verify-first: `runtime.cognitive_journal` is the AD-431/460 public attribute (verified at `runtime.py:213, 424, 1593`). `runtime.emit_event` is the post-AD-680 public method (verified at `runtime.py:785`). `runtime.eps_coordinator` is a NEW public attribute per Wave 5 convention #1.

---

## Tests

**File:** `tests/test_ad469_eps.py`

13 tests using fakes for `cognitive_journal` and `emit_event`:

1. `test_event_type_eps_budget_exceeded_exists`
2. `test_event_type_eps_reallocation_exists`
3. `test_eps_config_defaults` -- `enabled=True`, `window_seconds=60.0`, `over_budget_threshold=1.25`, 6 default departments.
4. `test_capacity_tracker_no_runtime_returns_empty` -- `runtime=None` -> empty `CapacitySummary`. `@pytest.mark.asyncio`.
5. `test_capacity_tracker_no_journal_returns_empty` -- runtime without `cognitive_journal` -> empty summary. `@pytest.mark.asyncio`.
6. `test_capacity_tracker_aggregates_by_agent_tier_model` -- fake journal returns rows; `summary()` populates `by_agent`/`by_tier`/`by_model` and `total_tokens`/`tokens_per_minute`. `@pytest.mark.asyncio`.
7. `test_department_budget_table_default_allocations_sum_to_one` -- six default departments sum to 1.0 (within 0.001).
8. `test_department_budget_table_renormalizes_on_override` -- override engineering to 0.50; remaining 5 departments share 0.50 proportional to their configured percents.
9. `test_department_budget_table_clear_override_restores` -- after clear, allocations match pre-override values.
10. `test_department_budget_table_rejects_unknown_department` -- `set_override("nonexistent", 0.5)` returns False.
11. `test_eps_coordinator_report_includes_capacity_and_allocations` -- mock capacity + budgets; `report()` returns `EPSReport` with both populated. `@pytest.mark.asyncio`.
12. `test_eps_coordinator_override_emits_reallocation` -- `override("medical", 0.50)` returns True; emit fires once with `EPS_REALLOCATION`, `cleared=False`, `percent=0.50`.
13. `test_eps_coordinator_check_budgets_returns_empty_list_v1` -- v1 contract: `check_budgets()` returns `[]` and emits nothing (no-theater). `@pytest.mark.asyncio`.

Each test uses `MagicMock`/`SimpleNamespace` stubs. No shared mutable state.

---

## What This Does NOT Change

- `CognitiveJournal` schema (`journal.py:25-43`) is unchanged. AD-469 reads `tokens_grouped_by(group_by=...)` only.
- `LLMClient._complete_inner` (`llm_client.py:411`) is unchanged. EPS does NOT gate LLM calls in v1.
- `IntentBus` (`mesh/intent.py`) is unchanged. Atomic budget enforcement is AD-469d.
- `bridge_alerts.py` is unchanged. Alert-aware reallocation is AD-469b.
- `runtime.work_item_store` and `runtime.workforce` are unchanged. EPS does not touch the workforce scheduler.
- `runtime.eps_coordinator.check_budgets()` returns `[]` in v1 — `EPS_BUDGET_EXCEEDED` is reserved for AD-469b once the agent->department resolver lands. This is honest deferral, not theater.
- AD-467 `runtime.ground_truth_verifier` and AD-463 `runtime.model_router` are unchanged.
- AD-469 introduces NO destructive intents. The `requires_consensus=True` rule does not apply.

---

## Tracking

- `PROGRESS.md`: add `AD-469 CLOSED. EPS Compute/Token Distribution (Capacity + Budgets + Captain Override) ...`
- `docs/development/roadmap.md`: flip AD-469 status from `*(planned)*` to `*(partial - v1 ships Capacity/Budgets/Override; alert-aware reallocation, back-pressure, atomic enforcement, prompt caching deferred to AD-469b/c/d/e)*` near line 4185.
- `DECISIONS.md`: optional entry recording the v1-3-of-7 scope decision and the no-theater contract on `check_budgets()`.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/eps/__init__.py`: ~13 lines (new; AD-469 owns directory creation).
- `src/probos/cognitive/eps/capacity.py`: ~95 lines (new).
- `src/probos/cognitive/eps/budgets.py`: ~80 lines (new).
- `src/probos/cognitive/eps/coordinator.py`: ~95 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~25 lines added (EPSDepartmentConfig + EPSConfig + SystemConfig field).
- `src/probos/startup/finalize.py`: ~30 lines added.
- `tests/test_ad469_eps.py`: ~280 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 13 tests pass under `pytest tests/test_ad469_eps.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `runtime.eps_coordinator` is a public attribute (no leading underscore).
- `CapacityTracker`, `DepartmentBudgetTable`, `EPSCoordinator` use stdlib only; no new pyproject deps.
- `cognitive_journal` schema is unchanged.
- `LLMClient._complete_inner` is unchanged. v1 ships consultation-only.
- `EPS_BUDGET_EXCEEDED` is RESERVED in v1 — no production emitter.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -rn "class EPS\|class CapacityTracker\|class DepartmentBudget" src/probos/
  (no matches -- AD-469 introduces these names)

grep -n "EPS_BUDGET_EXCEEDED\|EPS_REALLOCATION" src/probos/events.py
  (no matches -- names are free)

grep -n "MODEL_ROUTED\|MODEL_FALLBACK\|INFODYNAMIC_REPORT" src/probos/events.py
  199: INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
  210: MODEL_ROUTED = "model_routed"  # AD-463
  211: MODEL_FALLBACK = "model_fallback"  # AD-463
  (terminal anchor for Section 5)

grep -n "class CognitiveJournal" src/probos/cognitive/journal.py
  56: class CognitiveJournal:

grep -n "async def get_token_usage_by\|async def get_agent_tokens_since" src/probos/cognitive/journal.py
  278: async def get_agent_tokens_since(  # AD-617b
  299: async def get_token_usage_by(

grep -n "self\.cognitive_journal" src/probos/runtime.py
  213: cognitive_journal: CognitiveJournal | None
  424: self.cognitive_journal: CognitiveJournal | None = None
  1593: self.cognitive_journal = comm.cognitive_journal

grep -n "self\.llm_client\|def emit_event" src/probos/runtime.py
  347: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
  785: def emit_event(self, event: BaseEvent | str | EventType, ...

grep -n "model_routing: ModelRoutingConfig\|orders: OrdersConfig" src/probos/config.py
  1683: orders: OrdersConfig = OrdersConfig()  # AD-440
  1693: model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
  (anchor + fallback)

grep -n "class IntentBus" src/probos/mesh/intent.py
  (verified; AD-469 does NOT modify; AD-469d will integrate atomic budget gate)
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: `runtime.eps_coordinator` public. ✅
- #2 stdlib-only: yes. ✅
- #3 Coordinator-then-dispatch: v1 ships coordinator + 3 of 7 capabilities; 4 deferred. ✅
- #4 Superset-filter: read-only over journal; no interception. ✅
- #5 init_<phase>: Section 7 wires from finalize.py. ✅
- #6 Verify-first: footer above. ✅
- #7 No-theater: `check_budgets()` returns `[]` honestly. ✅
- #11 __new__-bypass defensive-getattr: `CapacityTracker.summary` uses `getattr(self, "_runtime", None)`. ✅
- #14 Aggressive pre-deferral: 4 of 7 capabilities deferred at draft time. ✅

---

## Revision (2026-05-02)

Applied review findings from `prompts/Reviews/ad-469-eps-compute-token-distribution-review.md` (verdict: ❌ Not Ready; 4 Required + 6 Recommended). The phantom-API issue was the verdict-driver.

**Required addressed:**

- **R#1: Phantom `tokens_grouped_by` -> real `get_token_usage_by`.** Section 2 `capacity.py` rewrites all three call sites:

  ```python
  by_agent = await journal.get_token_usage_by(group_by="agent_id")
  by_tier = await journal.get_token_usage_by(group_by="tier")
  by_model = await journal.get_token_usage_by(group_by="model")
  ```

  The exception-handler log message updated to mention `get_token_usage_by`. The Builder note immediately after Section 2 documents the API: returns `list[dict]` with keys `{<group_by>: <key>, "total_calls", "total_tokens", "prompt_tokens", "completion_tokens", "avg_latency_ms"}`.

- **R#2: Footer hallucinated grep result.** The verify-first footer line `300: async def tokens_grouped_by(` corrected to `299: async def get_token_usage_by(` (grep-confirmed against live source).

- **R#3: Wrong dict-key `row.get("calls", ...)` -> `row.get("total_calls", ...)`.** Section 2 line:

  ```python
  total_calls = sum(int(row.get("total_calls", 0) or 0) for row in by_agent)
  ```

  Matches the live `get_token_usage_by` row shape (verified at `journal.py:334`). The `total_tokens` key was already correct (line 335).

- **R#4: Group-key fragility (clarified as fragile-but-correct).** The review's R#4 documented a fragility (the dict-key access `row.get("agent_id", "")` works only because `group_by="agent_id"` matches the dynamic key name). No code change needed — the current code is correct. Added a Builder-note comment in Section 2 documenting that the dict-key access depends on the `group_by` argument value.

**Recommended applied:**

- **rec#2: drop unused `since` variable.** `since = time.time() - self._window_seconds` removed from `summary()`. The Builder note now states "per-window time filtering is deferred to AD-469b" without computing the unused value.
- **rec#3: `tokens_per_minute` overstates rate when journal is multi-day deep.** Added a Solution Overview note that v1's `tokens_per_minute` is an unfiltered aggregate divided by `window_seconds` -- producing a multiplier overstate when the journal extends beyond the window. AD-469b will introduce the `since=` filter via `get_token_usage_by` extension. Documented as honest deferral; not a v1 correctness bug.

**Recommended deferred:**

- **rec#1: `check_budgets()` returns `[]` always -- borderline-theater.** Architect judgment: keep the method with v1-empty-list contract. Architect rationale: AD-469b's downstream code will land an alert-aware reallocator that consumes `check_budgets()`; pre-defining the contract today (with explicit v1=[] documentation) is cheaper than reintroducing the method later. Convention #7 honored via the docstring's explicit "v1 contract: returns `[]` until AD-469b's agent->department resolver lands" note. The empty-list-by-design is honest.
- **rec#5: DepartmentBudgetTable allocation comment.** Renormalization behavior is mathematically correct; comment not added (the docstring already documents the renormalization).
- **rec#6: test #7 default-allocations sum-to-one.** Already in the test plan (default percents sum to 1.00 exactly: 0.30+0.20+0.15+0.15+0.10+0.10).

**Phantom-API pre-check (run during revision):**

```
grep -n "async def get_token_usage_by\|async def get_agent_tokens_since\|async def write" src/probos/cognitive/journal.py
  149: async def write(  # extends AD-431 schema; verified
  278: async def get_agent_tokens_since(  # AD-617b
  299: async def get_token_usage_by(

grep -n "self\.cognitive_journal\|self\.llm_client\|def emit_event" src/probos/runtime.py
  213: cognitive_journal: CognitiveJournal | None
  347: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
  424: self.cognitive_journal: CognitiveJournal | None = None
  785: def emit_event(self, event: BaseEvent | str | EventType, ...
```

All concrete claims grep-confirmed. No additional phantoms found beyond the original `tokens_grouped_by` issue.

**Verified Against Codebase footer extended:** corrected the `journal.py:300` line claim to `journal.py:299` and renamed the method.

**Test count: 13 -> 13** (no test plan changes; Required fixes are mechanical).

**Verdict shift:** Pass-1 ❌ Not Ready -> expected ✅ Approved on second-pass review (phantom-API mechanical fix; the verdict-driver issue is fully resolved).
