# AD-659c v1 — Chain Optimizer Counselor Watchdog + Decision Persistence

**Status:** ready
**Dependencies:** AD-659 (Wave 31, shipped), AD-659b (Wave 52, shipped at `b91dafe`), AD-658 (Wave 30, shipped — chain trace surface), AD-660 (Wave 32, shipped — counselor sibling pattern)
**Estimated tests:** 12 new (1 new test file `tests/test_ad659c_optimization_counselor.py`)
**Closes:** GH issue #410

---

## Problem

AD-659b (Wave 52) shipped the apply path (`apply_proposal()` mutates `runtime.config.chain_tuning.{low_trust_ceiling,high_trust_floor}`) and the manual revert path (`revert_proposal()` restores `pre_apply_value`). Three follow-up gaps remain — explicitly deferred from AD-659b's "Out of scope" section:

1. **No regression detection.** Once a proposal is applied, nothing watches whether the underlying chain-trace metrics actually improve. A bad proposal can degrade the system silently until the Captain notices.
2. **No automatic revert.** `revert_proposal()` exists but only fires on Captain command via `POST /apply/.../revert`. AD-659b explicitly defers auto-revert to AD-659c because it requires the watchdog.
3. **No EventType emission on apply/revert.** AD-659b's apply/revert paths log via `logger.info` only — there is no `OPTIMIZATION_PROPOSAL_APPLIED` event, so subscribers cannot react. AD-659b DLog #8: "Counselor watchdog wiring (AD-659c) will be the right surface to introduce `OPTIMIZATION_PROPOSAL_APPLIED` if needed."

Additionally, **watchdog decision persistence** is required so post-restart observability shows what the watchdog saw, what it decided, and why — without it the watchdog is a black box.

## Solution

v1 ships a self-contained `OptimizationCounselor` service that:

1. **Subscribes** to a new `OPTIMIZATION_PROPOSAL_APPLIED` event emitted from `ChainOptimizer.apply_proposal()`.
2. **Snapshots a pre-apply baseline** at apply time (success rate over the last `baseline_window_seconds` of chain traces).
3. **Schedules a delayed watchdog check** after `observation_window_seconds` (default 1800s = 30min) via `asyncio.create_task` + `asyncio.sleep` (cancellation-safe).
4. **Compares post-apply success rate vs baseline.** If `(baseline - post) >= success_rate_drop_floor` (default 0.10), records a regression; otherwise records "no regression".
5. **Optionally auto-reverts** the proposal via `runtime.chain_optimizer.revert_proposal(proposal_id, actor="optimization_counselor")` — gated by `auto_revert_enabled` (default `False`, Wave-10 convention #14).
6. **Persists every decision** (regression + no-regression + revert + skipped) to a new `optimization_decisions` table on `CognitiveJournal`.
7. **Emits `OPTIMIZATION_REGRESSION_DETECTED`** when a regression is recorded — Captain alert surface (no bridge alert in v1; HXI surface is AD-659c-1).
8. **Emits `OPTIMIZATION_PROPOSAL_REVERTED`** from `ChainOptimizer.revert_proposal()` (covers both Captain-driven and watchdog-driven reverts; the event payload distinguishes via `actor`).

### Scope

| Component | Status |
|---|---|
| 3 new EventTypes (`OPTIMIZATION_PROPOSAL_APPLIED`, `OPTIMIZATION_PROPOSAL_REVERTED`, `OPTIMIZATION_REGRESSION_DETECTED`) | NEW |
| Emission from `ChainOptimizer.apply_proposal()` | EDIT |
| Emission from `ChainOptimizer.revert_proposal()` | EDIT |
| `optimization_decisions` SQLite table on `CognitiveJournal` (INSERT-only; no upsert) | NEW |
| `record_optimization_decision()` + `get_recent_optimization_decisions()` on `CognitiveJournal` | NEW |
| `OptimizationCounselor` service in `cognitive/optimization_counselor.py` | NEW |
| `OptimizationDecision` frozen dataclass | NEW |
| `ChainOptimizerCounselorConfig` Pydantic model (default `enabled=False`, `auto_revert_enabled=False`) | NEW |
| `_wire_optimization_counselor` in `startup/finalize.py` (async wirer; calls `service.start()` to subscribe) | NEW |
| `runtime.optimization_counselor` public attribute | NEW |
| 12 new tests in `tests/test_ad659c_optimization_counselor.py` | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **p95 latency regression detection.** v1 watches success rate only. p95 latency drift is more sensitive to per-step variance and needs a wider baseline window. Deferred to AD-659c-1 with forcing function: AD-659c v1 ships and Captain validates success-rate detection accuracy in production.
- **Bridge alert / `BridgeAlert.deliver_bridge_alert()` integration.** v1 emits `OPTIMIZATION_REGRESSION_DETECTED` to the event log only. Routing it to the Bridge alert surface (AD-695 `ThresholdAlertService` pattern) is AD-659c-1 — requires `BridgeAlert` payload-shape contract for optimizer events that does not exist today (verified at `bridge_alerts.py`: existing alert_types are pool/degradation/attention only).
- **HXI surface for watchdog timeline.** AD-659c-2.
- **Statistical confidence interval** on success-rate comparison (e.g. Wilson score). v1 uses a flat 0.10 absolute drop floor. Deferred AD-659c-1.
- **`CounselorAgent` integration.** The watchdog is a standalone service, NOT a method on `CounselorAgent`. `CounselorAgent` is an event-handler-saturated cognitive agent (verified: ~25 `_on_*` event handlers at `counselor.py:932-1727`); adding optimizer-regression handling there would couple a chain-tuning concern to a crew-wellness agent. The `OptimizationCounselor` service runs adjacent (sibling pattern to `ThresholdAlertService` AD-695).
- **Warm-boot replay of in-flight watchdog timers.** If a `apply_proposal()` fires and the process restarts before the observation window elapses, the watchdog check is lost. The persisted `optimization_decisions` row exists only after the check completes. Deferred AD-659c-3 with forcing function: persistent watchdog requires a durable timer surface (none exists at HEAD — verified zero `runtime.timer_service` matches).
- **Multiple concurrent watchdog windows for the same `proposal_id`.** v1 tracks at most one in-flight watchdog per proposal (idempotent via `_pending_checks: dict[proposal_id, asyncio.Task]`). Re-applying after revert is a new proposal_id; not a re-arm of the same one.
- **No new Pydantic config beyond `ChainOptimizerCounselorConfig`. No new pool. No new agent. No new module beyond `cognitive/optimization_counselor.py`. No `CounselorAgent` changes.**

---

## Verified Against Codebase (HEAD post-Wave-52, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `ChainOptimizer.apply_proposal(proposal_id, *, actor="captain") -> OptimizationProposal` | `cognitive/chain_optimizer.py` | 318 | `async def apply_proposal(` |
| `ChainOptimizer.revert_proposal(proposal_id, *, actor="captain") -> OptimizationProposal` | `cognitive/chain_optimizer.py` | 379 | `async def revert_proposal(` |
| `ChainOptimizer.emit_event` public field | `cognitive/chain_optimizer.py` | 230 | `self.emit_event = emit_event` |
| `ChainOptimizerConfig` (10 fields incl. `apply_enabled`, `analysis_interval_seconds`) | `config.py` | 336-362 | model body + field_validator |
| `SystemConfig.chain_optimizer` | `config.py` | 2287 | `chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659` |
| `SystemConfig.causal_reasoning` (insertion-anchor sibling) | `config.py` | 2288 | `causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660` |
| `_wire_chain_optimizer` wirer | `startup/finalize.py` | 214 | `def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:` |
| `_wire_chain_optimizer` cascade slot | `startup/finalize.py` | 871 | `if _wire_chain_optimizer(runtime=runtime, config=config):` |
| `_wire_causal_reasoner` cascade slot (insertion-anchor sibling) | `startup/finalize.py` | 880 | `if _wire_causal_reasoner(runtime=runtime, config=config):` |
| `runtime.emit_event(event, data=None)` public method | `runtime.py` | 816 | `def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:` |
| `runtime.add_event_listener(...)` public method | `runtime.py` | 683 | `def add_event_listener(` |
| `CognitiveJournal._SCHEMA_OPTIMIZATION_PROPOSALS` precedent | `cognitive/journal.py` | 117 | `_SCHEMA_OPTIMIZATION_PROPOSALS = """` |
| `CognitiveJournal.start()` schema execution chain | `cognitive/journal.py` | 192 | `await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)` |
| `CognitiveJournal.record_optimization_proposal(proposal)` (insertion-anchor sibling) | `cognitive/journal.py` | 416 | `async def record_optimization_proposal(self, proposal: Any) -> None:` |
| `CognitiveJournal.get_optimization_proposal(proposal_id)` (insertion-anchor sibling) | `cognitive/journal.py` | 487 | `async def get_optimization_proposal(self, proposal_id: str) -> dict[str, Any] | None:` |
| `EventType.MCP_BRIDGE_FAILED` (insertion-anchor sibling — last AD-449 enum entry) | `events.py` | 230 | `MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449` |
| `EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED` (verified end-of-enum block) | `events.py` | 231 | `OBSERVABILITY_SNAPSHOT_PUBLISHED = "observability_snapshot_published"  # AD-641a` |
| `EventType.SELF_MONITORING_CONCERN` (existing precedent, AD-660 hook) | `events.py` | 127 | `SELF_MONITORING_CONCERN = "self_monitoring_concern"  # AD-506a: amber zone` |
| `_wire_causal_reasoner` async/sync shape | `startup/finalize.py` | 366 | `def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:` (sync) |
| `OptimizationProposal` mutable dataclass with `applied`/`pre_apply_value` | `cognitive/chain_optimizer.py` | 22-50 | dataclass body |

`OPTIMIZATION_PROPOSAL_APPLIED`, `OPTIMIZATION_PROPOSAL_REVERTED`, `OPTIMIZATION_REGRESSION_DETECTED`, `optimization_counselor`, `optimization_decisions`, `OptimizationCounselor`, `OptimizationDecision`, `ChainOptimizerCounselorConfig`, `record_optimization_decision`, `get_recent_optimization_decisions`, `_wire_optimization_counselor` — all greenfield, verified zero hits at HEAD `b91dafe`.

---

## Implementation

### Section 0 — Three new EventTypes

**File:** `src/probos/events.py`

`SEARCH` block (around line 229-231):
```python
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
    OBSERVABILITY_SNAPSHOT_PUBLISHED = "observability_snapshot_published"  # AD-641a
```

`REPLACE`:
```python
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
    OPTIMIZATION_PROPOSAL_APPLIED = "optimization_proposal_applied"  # AD-659c
    OPTIMIZATION_PROPOSAL_REVERTED = "optimization_proposal_reverted"  # AD-659c
    OPTIMIZATION_REGRESSION_DETECTED = "optimization_regression_detected"  # AD-659c
    OBSERVABILITY_SNAPSHOT_PUBLISHED = "observability_snapshot_published"  # AD-641a
```

No structured `BaseEvent` subclass needed (AD-659c emits via dict-payload `runtime.emit_event(EventType.X, {...})` — same shape as AD-660 / AD-641a / AD-695 / AD-449 sibling emissions).

---

### Section 1a — Emit `OPTIMIZATION_PROPOSAL_APPLIED` from `apply_proposal()`

**File:** `src/probos/cognitive/chain_optimizer.py`

`SEARCH` block (the trailing `logger.info` + `return proposal` at the end of `apply_proposal`, around line 372-377):
```python
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: applied proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            proposal.pre_apply_value, proposal.proposed_value, actor,
        )
        return proposal
```

`REPLACE`:
```python
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: applied proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            proposal.pre_apply_value, proposal.proposed_value, actor,
        )
        # AD-659c: emit event so OptimizationCounselor watchdog can snapshot baseline.
        if self.emit_event is not None:
            try:
                from probos.events import EventType as _ET
                self.emit_event(_ET.OPTIMIZATION_PROPOSAL_APPLIED, {
                    "proposal_id": proposal.proposal_id,
                    "target_parameter": proposal.target_parameter,
                    "pre_apply_value": proposal.pre_apply_value,
                    "proposed_value": proposal.proposed_value,
                    "detector_name": proposal.detector_name,
                    "actor": actor,
                    "applied_at": proposal.applied_at,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_PROPOSAL_APPLIED failed",
                    exc_info=True,
                )
        return proposal
```

### Section 1b — Emit `OPTIMIZATION_PROPOSAL_REVERTED` from `revert_proposal()`

`SEARCH` block (the trailing `logger.info` + `return proposal` at the end of `revert_proposal`, around line 411-416):
```python
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: reverted proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            prior_value, proposal.pre_apply_value, actor,
        )
        return proposal
```

`REPLACE`:
```python
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: reverted proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            prior_value, proposal.pre_apply_value, actor,
        )
        # AD-659c: emit event for audit trail (covers Captain-driven and
        # watchdog-driven reverts; actor distinguishes).
        if self.emit_event is not None:
            try:
                from probos.events import EventType as _ET
                self.emit_event(_ET.OPTIMIZATION_PROPOSAL_REVERTED, {
                    "proposal_id": proposal.proposal_id,
                    "target_parameter": proposal.target_parameter,
                    "reverted_to": proposal.pre_apply_value,
                    "from_value": prior_value,
                    "detector_name": proposal.detector_name,
                    "actor": actor,
                    "reverted_at": proposal.applied_at,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_PROPOSAL_REVERTED failed",
                    exc_info=True,
                )
        return proposal
```

---

### Section 2 — `optimization_decisions` schema + 2 CRUD methods on `CognitiveJournal`

**File:** `src/probos/cognitive/journal.py`

`SEARCH` block (the `_SCHEMA_OPTIMIZATION_PROPOSALS` constant, around line 117-138 — locate the closing `"""` of this constant; insert the new schema immediately after):

Insert this block immediately after the closing `"""` of `_SCHEMA_OPTIMIZATION_PROPOSALS` (around line 138, before the next module-level construct):

```python
# AD-659c: OptimizationCounselor watchdog decision audit trail (net-new table).
_SCHEMA_OPTIMIZATION_DECISIONS = """
CREATE TABLE IF NOT EXISTS optimization_decisions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id        TEXT NOT NULL DEFAULT '',
    decided_at         REAL NOT NULL DEFAULT 0.0,
    decision           TEXT NOT NULL DEFAULT '',
    baseline_success_rate REAL,
    post_success_rate  REAL,
    drop_amount        REAL,
    sample_count_baseline INTEGER NOT NULL DEFAULT 0,
    sample_count_post  INTEGER NOT NULL DEFAULT 0,
    auto_revert_attempted INTEGER NOT NULL DEFAULT 0,
    auto_revert_succeeded INTEGER NOT NULL DEFAULT 0,
    detail             TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_optimization_decisions_proposal
    ON optimization_decisions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_optimization_decisions_decided_at
    ON optimization_decisions(decided_at);
"""
```

Then in the `start()` method, immediately after the existing AD-659b `await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)` line at journal.py:192, add the new schema execution.

`SEARCH` block (around line 191-194):
```python
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        await self._db.commit()
```

`REPLACE`:
```python
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        # AD-659c: OptimizationCounselor watchdog decisions (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_DECISIONS)
        await self._db.commit()
```

Now add two new CRUD methods on `CognitiveJournal`. Insert them immediately after `get_optimization_proposal` (around line 497 — before `record_causal_template`).

`SEARCH` block (the closing `return None` of `get_optimization_proposal` plus the next method `async def record_causal_template`, around line 495-501):
```python
            return dict(row) if row else None
        except Exception:
            logger.debug("AD-659b: proposal fetch failed", exc_info=True)
            return None

    async def record_causal_template(self, template: Any) -> None:
```

`REPLACE`:
```python
            return dict(row) if row else None
        except Exception:
            logger.debug("AD-659b: proposal fetch failed", exc_info=True)
            return None

    async def record_optimization_decision(
        self,
        *,
        proposal_id: str,
        decided_at: float,
        decision: str,
        baseline_success_rate: float | None = None,
        post_success_rate: float | None = None,
        drop_amount: float | None = None,
        sample_count_baseline: int = 0,
        sample_count_post: int = 0,
        auto_revert_attempted: bool = False,
        auto_revert_succeeded: bool = False,
        detail: str = "",
    ) -> None:
        """AD-659c: Persist a single OptimizationCounselor watchdog decision.

        INSERT-only (no upsert). Each watchdog observation is a new row.
        Fire-and-forget — never raises.
        """
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO optimization_decisions
                   (proposal_id, decided_at, decision,
                    baseline_success_rate, post_success_rate, drop_amount,
                    sample_count_baseline, sample_count_post,
                    auto_revert_attempted, auto_revert_succeeded, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id,
                    decided_at,
                    decision,
                    baseline_success_rate,
                    post_success_rate,
                    drop_amount,
                    sample_count_baseline,
                    sample_count_post,
                    1 if auto_revert_attempted else 0,
                    1 if auto_revert_succeeded else 0,
                    detail,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-659c: optimization decision record failed", exc_info=True)

    async def get_recent_optimization_decisions(
        self,
        *,
        limit: int = 50,
        proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """AD-659c: Return recent watchdog decisions, newest-first.

        Optional `proposal_id` filter for per-proposal audit lookups.
        """
        if not self._db:
            return []
        try:
            if proposal_id is not None:
                cursor = await self._db.execute(
                    "SELECT * FROM optimization_decisions "
                    "WHERE proposal_id = ? ORDER BY decided_at DESC LIMIT ?",
                    (proposal_id, limit),
                )
            else:
                cursor = await self._db.execute(
                    "SELECT * FROM optimization_decisions "
                    "ORDER BY decided_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("AD-659c: optimization decisions query failed", exc_info=True)
            return []

    async def record_causal_template(self, template: Any) -> None:
```

---

### Section 3 — New `OptimizationCounselor` service

**File:** `src/probos/cognitive/optimization_counselor.py` (NEW — full file content):

```python
"""OptimizationCounselor — watchdog for AD-659b ChainOptimizer apply path.

AD-659c v1: subscribes to OPTIMIZATION_PROPOSAL_APPLIED events; for each
applied proposal, snapshots a pre-apply success-rate baseline from
`runtime.cognitive_journal` chain traces, schedules a delayed watchdog check,
compares post-apply metrics to baseline, persists the decision, optionally
auto-reverts (gated by `auto_revert_enabled`, default False).

The counselor never raises into the runtime — every external call is wrapped
in tier-2 log-and-degrade.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimizationDecision:
    """Single watchdog decision record (audit trail row)."""

    proposal_id: str
    decided_at: float
    decision: str  # "regression" | "no_regression" | "skipped" | "revert_failed"
    baseline_success_rate: float | None = None
    post_success_rate: float | None = None
    drop_amount: float | None = None
    sample_count_baseline: int = 0
    sample_count_post: int = 0
    auto_revert_attempted: bool = False
    auto_revert_succeeded: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _success_rate(traces: list[dict[str, Any]]) -> tuple[float, int]:
    """Return (success_rate, sample_count) from a list of chain trace rows.

    success_rate is 0.0 when sample_count is 0.
    """
    n = len(traces)
    if n == 0:
        return (0.0, 0)
    succ = sum(1 for r in traces if int(bool(r.get("success", 0))))
    return (succ / n, n)


class OptimizationCounselor:
    """Watchdog for AD-659b applied proposals (AD-659c v1).

    Lifecycle:
        await counselor.start()  # subscribes to OPTIMIZATION_PROPOSAL_APPLIED
        await counselor.stop()   # cancels in-flight watchdog tasks

    Flow per applied proposal:
        1. _on_apply_event captures baseline success rate from chain traces
           (last `baseline_window_seconds` before applied_at).
        2. Schedules `_watchdog_check(proposal_id, baseline_rate, baseline_n)`
           via asyncio.create_task with `await asyncio.sleep(observation_window_seconds)`.
        3. Watchdog reads chain traces from applied_at to now, computes post
           success rate, compares to baseline.
        4. If `(baseline - post) >= success_rate_drop_floor`, records a
           regression decision + emits OPTIMIZATION_REGRESSION_DETECTED.
        5. If `auto_revert_enabled` AND regression detected, calls
           `runtime.chain_optimizer.revert_proposal(proposal_id, actor="optimization_counselor")`.
        6. Persists the decision to runtime.cognitive_journal.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        baseline_window_seconds: float = 1800.0,
        observation_window_seconds: float = 1800.0,
        success_rate_drop_floor: float = 0.10,
        min_samples_per_window: int = 20,
        auto_revert_enabled: bool = False,
    ) -> None:
        self._runtime = runtime
        self._baseline_window_seconds = float(baseline_window_seconds)
        self._observation_window_seconds = float(observation_window_seconds)
        self._success_rate_drop_floor = float(success_rate_drop_floor)
        self._min_samples_per_window = int(min_samples_per_window)
        self._auto_revert_enabled = bool(auto_revert_enabled)
        # In-flight watchdog tasks per proposal_id (idempotent: re-applied
        # proposals get a new proposal_id; same id during an in-flight window
        # is a no-op replace).
        self._pending_checks: dict[str, asyncio.Task[None]] = {}
        self._listener_attached: bool = False

    async def start(self) -> None:
        """Subscribe to OPTIMIZATION_PROPOSAL_APPLIED events.

        Idempotent — calling twice is a no-op.
        """
        if self._listener_attached:
            return
        from probos.events import EventType
        add_listener = getattr(self._runtime, "add_event_listener", None)
        if add_listener is None:
            logger.warning(
                "AD-659c: runtime.add_event_listener unavailable; "
                "OptimizationCounselor inert"
            )
            return
        try:
            add_listener(
                self._on_apply_event_async,
                event_types=[EventType.OPTIMIZATION_PROPOSAL_APPLIED],
            )
            self._listener_attached = True
        except Exception:
            logger.warning(
                "AD-659c: failed to attach OPTIMIZATION_PROPOSAL_APPLIED listener",
                exc_info=True,
            )

    async def stop(self) -> None:
        """Cancel any in-flight watchdog tasks. Idempotent."""
        tasks = list(self._pending_checks.values())
        self._pending_checks.clear()
        for task in tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    async def _on_apply_event_async(self, event: dict[str, Any]) -> None:
        """Snapshot baseline + schedule watchdog check.

        Event shape (per Section 1a emission):
            {"event_type": "...", "data": {"proposal_id", "applied_at", ...}}
        Some runtimes pass the data dict directly. Tolerate both.
        """
        try:
            data = event.get("data", event) if isinstance(event, dict) else {}
            proposal_id = str(data.get("proposal_id", ""))
            applied_at = float(data.get("applied_at") or time.time())
            if not proposal_id:
                return
            # Snapshot baseline.
            baseline_rate, baseline_n = await self._compute_success_rate_window(
                end_time=applied_at,
                window_seconds=self._baseline_window_seconds,
            )
            # Schedule watchdog. If a check already pending for this id,
            # cancel the old one (last-event-wins).
            existing = self._pending_checks.pop(proposal_id, None)
            if existing is not None and not existing.done():
                existing.cancel()
            task = asyncio.create_task(
                self._watchdog_check(
                    proposal_id=proposal_id,
                    baseline_rate=baseline_rate,
                    baseline_n=baseline_n,
                    applied_at=applied_at,
                )
            )
            self._pending_checks[proposal_id] = task
        except Exception:
            logger.warning(
                "AD-659c: _on_apply_event_async failed",
                exc_info=True,
            )

    async def _compute_success_rate_window(
        self,
        *,
        end_time: float,
        window_seconds: float,
    ) -> tuple[float, int]:
        """Pull chain traces for the [end_time - window, end_time] interval
        from runtime.cognitive_journal and return (success_rate, sample_count).

        Returns (0.0, 0) on any failure or when journal unavailable.
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return (0.0, 0)
        try:
            # Over-fetch by limit; filter by started_at in Python because
            # get_recent_chain_traces may not honor a `since` upper bound.
            traces = await journal.get_recent_chain_traces(limit=500)
        except Exception:
            return (0.0, 0)
        start = end_time - window_seconds
        windowed = [
            r for r in traces
            if start <= float(r.get("started_at", 0.0)) <= end_time
        ]
        return _success_rate(windowed)

    async def _watchdog_check(
        self,
        *,
        proposal_id: str,
        baseline_rate: float,
        baseline_n: int,
        applied_at: float,
    ) -> None:
        """Sleep observation_window_seconds, then evaluate post-apply metrics.

        Cancellation-safe — re-raises CancelledError after cleanup.
        """
        try:
            await asyncio.sleep(self._observation_window_seconds)
        except asyncio.CancelledError:
            self._pending_checks.pop(proposal_id, None)
            raise
        try:
            now = time.time()
            post_rate, post_n = await self._compute_success_rate_window(
                end_time=now,
                window_seconds=self._observation_window_seconds,
            )
            await self._evaluate_and_record(
                proposal_id=proposal_id,
                baseline_rate=baseline_rate,
                baseline_n=baseline_n,
                post_rate=post_rate,
                post_n=post_n,
                decided_at=now,
            )
        except Exception:
            logger.warning(
                "AD-659c: _watchdog_check evaluation failed for %s",
                proposal_id, exc_info=True,
            )
        finally:
            self._pending_checks.pop(proposal_id, None)

    async def _evaluate_and_record(
        self,
        *,
        proposal_id: str,
        baseline_rate: float,
        baseline_n: int,
        post_rate: float,
        post_n: int,
        decided_at: float,
    ) -> None:
        """Decide regression/no_regression/skipped, persist, optionally revert."""
        journal = getattr(self._runtime, "cognitive_journal", None)
        # Insufficient samples → skipped (not a regression signal).
        if (
            baseline_n < self._min_samples_per_window
            or post_n < self._min_samples_per_window
        ):
            decision = OptimizationDecision(
                proposal_id=proposal_id,
                decided_at=decided_at,
                decision="skipped",
                baseline_success_rate=baseline_rate if baseline_n else None,
                post_success_rate=post_rate if post_n else None,
                drop_amount=None,
                sample_count_baseline=baseline_n,
                sample_count_post=post_n,
                detail=(
                    f"insufficient samples (baseline={baseline_n}, "
                    f"post={post_n}, floor={self._min_samples_per_window})"
                ),
            )
            await self._persist(decision, journal)
            return
        drop = baseline_rate - post_rate
        is_regression = drop >= self._success_rate_drop_floor
        if not is_regression:
            decision = OptimizationDecision(
                proposal_id=proposal_id,
                decided_at=decided_at,
                decision="no_regression",
                baseline_success_rate=baseline_rate,
                post_success_rate=post_rate,
                drop_amount=drop,
                sample_count_baseline=baseline_n,
                sample_count_post=post_n,
                detail=f"drop={drop:.3f} below floor {self._success_rate_drop_floor:.3f}",
            )
            await self._persist(decision, journal)
            return
        # Regression detected.
        revert_attempted = False
        revert_succeeded = False
        revert_detail = ""
        if self._auto_revert_enabled:
            optimizer = getattr(self._runtime, "chain_optimizer", None)
            if optimizer is not None:
                revert_attempted = True
                try:
                    await optimizer.revert_proposal(
                        proposal_id, actor="optimization_counselor",
                    )
                    revert_succeeded = True
                except Exception as exc:
                    revert_detail = f"revert raised: {type(exc).__name__}: {exc}"
                    logger.warning(
                        "AD-659c: auto-revert failed for %s",
                        proposal_id, exc_info=True,
                    )
        decision_label = (
            "revert_failed"
            if revert_attempted and not revert_succeeded
            else "regression"
        )
        decision = OptimizationDecision(
            proposal_id=proposal_id,
            decided_at=decided_at,
            decision=decision_label,
            baseline_success_rate=baseline_rate,
            post_success_rate=post_rate,
            drop_amount=drop,
            sample_count_baseline=baseline_n,
            sample_count_post=post_n,
            auto_revert_attempted=revert_attempted,
            auto_revert_succeeded=revert_succeeded,
            detail=(
                revert_detail
                or f"drop={drop:.3f} >= floor {self._success_rate_drop_floor:.3f}"
            ),
        )
        await self._persist(decision, journal)
        # Emit regression event for downstream subscribers.
        emit_event = getattr(self._runtime, "emit_event", None)
        if emit_event is not None:
            try:
                from probos.events import EventType
                emit_event(EventType.OPTIMIZATION_REGRESSION_DETECTED, {
                    "proposal_id": proposal_id,
                    "baseline_success_rate": baseline_rate,
                    "post_success_rate": post_rate,
                    "drop_amount": drop,
                    "auto_revert_attempted": revert_attempted,
                    "auto_revert_succeeded": revert_succeeded,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_REGRESSION_DETECTED failed",
                    exc_info=True,
                )

    async def _persist(
        self, decision: OptimizationDecision, journal: Any,
    ) -> None:
        """Record decision via journal.record_optimization_decision (best-effort)."""
        if journal is None:
            return
        try:
            await journal.record_optimization_decision(**decision.to_dict())
        except Exception:
            logger.debug(
                "AD-659c: _persist failed for %s",
                decision.proposal_id, exc_info=True,
            )
```

---

### Section 4 — `ChainOptimizerCounselorConfig` Pydantic model + `SystemConfig` field

**File:** `src/probos/config.py`

Insert immediately after `ChainOptimizerConfig` (around line 363, before `class CausalReasoningConfig` at line 416 — anchor with the field_validator close of ChainOptimizerConfig).

`SEARCH` block (around line 357-364 — the closing `_validate_interval` validator + blank line before next class):
```python
    apply_enabled: bool = False  # AD-659b: apply path gate (default OFF)
    analysis_interval_seconds: int = 0  # AD-659b: 0 disables scheduled loop

    @field_validator("analysis_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("analysis_interval_seconds must be >= 0")
        return v
```

`REPLACE`:
```python
    apply_enabled: bool = False  # AD-659b: apply path gate (default OFF)
    analysis_interval_seconds: int = 0  # AD-659b: 0 disables scheduled loop

    @field_validator("analysis_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("analysis_interval_seconds must be >= 0")
        return v


class ChainOptimizerCounselorConfig(BaseModel):
    """AD-659c v1: OptimizationCounselor watchdog for AD-659b applied proposals.

    Default-OFF (Wave-10 convention #14). Captain opts in once AD-659b apply
    has accumulated production data and detection accuracy is validated.

    `auto_revert_enabled` is a SECOND gate — the watchdog can be enabled to
    only observe + record decisions (no destructive action) without granting
    revert authority. Captain flips auto_revert separately once observed
    decisions look correct.
    """

    enabled: bool = False
    baseline_window_seconds: float = 1800.0       # 30 min
    observation_window_seconds: float = 1800.0    # 30 min
    success_rate_drop_floor: float = 0.10         # 10% absolute drop
    min_samples_per_window: int = 20
    auto_revert_enabled: bool = False             # SECOND gate

    @field_validator(
        "baseline_window_seconds",
        "observation_window_seconds",
    )
    @classmethod
    def _validate_window(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError("window seconds must be > 0")
        return v

    @field_validator("success_rate_drop_floor")
    @classmethod
    def _validate_drop_floor(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("success_rate_drop_floor must be in [0.0, 1.0]")
        return v

    @field_validator("min_samples_per_window")
    @classmethod
    def _validate_min_samples(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_per_window must be >= 1")
        return v
```

Then wire onto `SystemConfig`. `SEARCH` block (around line 2287-2288):
```python
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
```

`REPLACE`:
```python
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
    chain_optimizer_counselor: ChainOptimizerCounselorConfig = ChainOptimizerCounselorConfig()  # AD-659c
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
```

---

### Section 5 — `_wire_optimization_counselor` async wirer + cascade slot

**File:** `src/probos/startup/finalize.py`

Insert the wirer immediately after `_wire_chain_optimizer` (which ends around line 263 with `return True`). The new wirer is **async** because `service.start()` is async.

`SEARCH` block (the closing `return True` of `_wire_chain_optimizer`, around line 257-265):
```python
    logger.info(
        "AD-659b: ChainOptimizer initialized (apply_enabled=%s, "
        "analysis_interval_seconds=%s)",
        apply_enabled,
        interval_int,
    )
    return True


async def _wire_edge_backfill(*, runtime: Any, config: "SystemConfig") -> bool:
```

`REPLACE`:
```python
    logger.info(
        "AD-659b: ChainOptimizer initialized (apply_enabled=%s, "
        "analysis_interval_seconds=%s)",
        apply_enabled,
        interval_int,
    )
    return True


async def _wire_optimization_counselor(
    *, runtime: Any, config: "SystemConfig",
) -> bool:
    """AD-659c v1: Wire OptimizationCounselor watchdog for AD-659b apply path."""
    cfg = getattr(config, "chain_optimizer_counselor", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.optimization_counselor import OptimizationCounselor

    counselor = OptimizationCounselor(
        runtime,
        baseline_window_seconds=cfg.baseline_window_seconds,
        observation_window_seconds=cfg.observation_window_seconds,
        success_rate_drop_floor=cfg.success_rate_drop_floor,
        min_samples_per_window=cfg.min_samples_per_window,
        auto_revert_enabled=cfg.auto_revert_enabled,
    )
    runtime.optimization_counselor = counselor  # public attribute (Wave 5 conv #1)
    try:
        await counselor.start()
    except Exception:
        logger.warning(
            "AD-659c: OptimizationCounselor.start() failed", exc_info=True,
        )
    logger.info(
        "AD-659c: OptimizationCounselor initialized "
        "(auto_revert_enabled=%s, observation_window=%.1fs, drop_floor=%.2f)",
        cfg.auto_revert_enabled,
        cfg.observation_window_seconds,
        cfg.success_rate_drop_floor,
    )
    return True


async def _wire_edge_backfill(*, runtime: Any, config: "SystemConfig") -> bool:
```

Now add the cascade slot. `SEARCH` block (around line 871 — `_wire_chain_optimizer` invocation):
```python
    if _wire_chain_optimizer(runtime=runtime, config=config):
```

The replace must add a new slot AFTER the `if _wire_chain_optimizer(...)` block. Find the closing line of that if-block and insert. Use the broader context:

`SEARCH` block (the `_wire_chain_optimizer` cascade invocation block; locate the surrounding `if _wire_causal_reasoner` 9 lines later for a unique anchor):
```python
    if _wire_chain_optimizer(runtime=runtime, config=config):
        wired_phases.append("chain_optimizer")
```

`REPLACE`:
```python
    if _wire_chain_optimizer(runtime=runtime, config=config):
        wired_phases.append("chain_optimizer")

    if await _wire_optimization_counselor(runtime=runtime, config=config):
        wired_phases.append("optimization_counselor")
```

> **NOTE FOR BUILDER:** The `_wire_chain_optimizer` cascade slot at finalize.py:871 reads `if _wire_chain_optimizer(runtime=runtime, config=config):` followed by an append-to-`wired_phases` line. Verify the next line is the append before applying SEARCH/REPLACE. If the surrounding append-line shape has drifted, fall back to inserting the new `await _wire_optimization_counselor(...)` block immediately AFTER the `_wire_chain_optimizer` invocation but BEFORE `_wire_causal_reasoner` (line 880). The cascade is order-sensitive only in that the counselor depends on chain_optimizer being wired first (subscribes to its events) — counselor must be wired AFTER chain_optimizer.

---

### Section 6 — Tests

**File:** `tests/test_ad659c_optimization_counselor.py` (NEW — full file content):

```python
"""AD-659c — OptimizationCounselor watchdog + decision persistence.

Tests:
  1. EventType registration: 3 new values present, exact string values.
  2. ChainOptimizer.apply_proposal emits OPTIMIZATION_PROPOSAL_APPLIED with
     full payload (proposal_id, target_parameter, pre/proposed values, actor).
  3. ChainOptimizer.revert_proposal emits OPTIMIZATION_PROPOSAL_REVERTED.
  4. Journal record_optimization_decision + get_recent_optimization_decisions
     round-trip with real CognitiveJournal against tmp_path (all 11 fields).
  5. Journal get_recent_optimization_decisions filters by proposal_id.
  6. OptimizationDecision frozen + to_dict round-trip.
  7. _compute_success_rate_window filters traces by [end_time - window, end_time].
  8. _evaluate_and_record records "skipped" when baseline_n < min_samples.
  9. _evaluate_and_record records "no_regression" when drop < floor.
 10. _evaluate_and_record records "regression" when drop >= floor; emits
     OPTIMIZATION_REGRESSION_DETECTED; does NOT call revert when
     auto_revert_enabled=False.
 11. _evaluate_and_record records "regression" + calls
     optimizer.revert_proposal when auto_revert_enabled=True; auto_revert_succeeded=1.
 12. ChainOptimizerCounselorConfig defaults; field validators reject bad values.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.chain_optimizer import (
    ChainOptimizer,
    OptimizationProposal,
)
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.optimization_counselor import (
    OptimizationCounselor,
    OptimizationDecision,
)
from probos.config import ChainOptimizerCounselorConfig
from probos.events import EventType


def _make_runtime_with_chain_tuning():
    """Real ChainTuningConfig wrapped in a runtime stub."""
    from probos.config import ChainTuningConfig
    return SimpleNamespace(chain_tuning=ChainTuningConfig())


def _trace(*, started_at: float, success: int = 1) -> dict:
    return {
        "chain_id": "c", "step_index": 0, "step_name": "comprehend",
        "sub_task_type": "comprehend", "tier": "standard",
        "chain_source": "user_request", "agent_id": "a", "agent_type": "t",
        "intent": "x", "intent_id": "i",
        "started_at": started_at, "duration_ms": 500.0, "tokens_used": 0,
        "success": success, "error_truncated": "",
        "context_keys_declared": "", "context_keys_passed": "",
        "context_filter_applied": 0, "communication_context": "formal",
        "chain_trust_band": "mid", "trust_score": 0.5,
        "boot_camp_active": 0, "from_captain": 0, "is_dm": 0,
    }


# 1 ----------------------------------------------------------------------

def test_event_types_registered():
    assert EventType.OPTIMIZATION_PROPOSAL_APPLIED.value == "optimization_proposal_applied"
    assert EventType.OPTIMIZATION_PROPOSAL_REVERTED.value == "optimization_proposal_reverted"
    assert EventType.OPTIMIZATION_REGRESSION_DETECTED.value == "optimization_regression_detected"


# 2 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_proposal_emits_applied_event():
    config = _make_runtime_with_chain_tuning()
    runtime = SimpleNamespace(cognitive_journal=None, config=config)
    captured: list[tuple] = []

    def emit(event_type, data):
        captured.append((event_type, data))

    opt = ChainOptimizer(runtime, apply_enabled=True, emit_event=emit)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
        decision="approve",
    )
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id, actor="captain")
    assert len(captured) == 1
    et, payload = captured[0]
    assert et == EventType.OPTIMIZATION_PROPOSAL_APPLIED
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["target_parameter"] == "chain_tuning.low_trust_ceiling"
    assert payload["pre_apply_value"] == 0.60
    assert payload["proposed_value"] == 0.65
    assert payload["actor"] == "captain"
    assert payload["detector_name"] == "success_rate_floor_breach"


# 3 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_proposal_emits_reverted_event():
    config = _make_runtime_with_chain_tuning()
    runtime = SimpleNamespace(cognitive_journal=None, config=config)
    captured: list[tuple] = []

    def emit(event_type, data):
        captured.append((event_type, data))

    opt = ChainOptimizer(runtime, apply_enabled=True, emit_event=emit)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.high_trust_floor",
        current_value=0.75, proposed_value=0.80,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="d",
        decision="approve",
    )
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    captured.clear()
    await opt.revert_proposal(proposal.proposal_id, actor="optimization_counselor")
    assert len(captured) == 1
    et, payload = captured[0]
    assert et == EventType.OPTIMIZATION_PROPOSAL_REVERTED
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["actor"] == "optimization_counselor"
    assert payload["reverted_to"] == 0.75
    assert payload["from_value"] == 0.80


# 4 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_decision_roundtrip(tmp_path: Path):
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        await journal.record_optimization_decision(
            proposal_id="p1",
            decided_at=12345.0,
            decision="regression",
            baseline_success_rate=0.85,
            post_success_rate=0.65,
            drop_amount=0.20,
            sample_count_baseline=50,
            sample_count_post=45,
            auto_revert_attempted=True,
            auto_revert_succeeded=True,
            detail="drop=0.20 >= floor 0.10",
        )
        rows = await journal.get_recent_optimization_decisions(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["proposal_id"] == "p1"
        assert row["decision"] == "regression"
        assert row["baseline_success_rate"] == pytest.approx(0.85)
        assert row["post_success_rate"] == pytest.approx(0.65)
        assert row["drop_amount"] == pytest.approx(0.20)
        assert row["sample_count_baseline"] == 50
        assert row["sample_count_post"] == 45
        assert row["auto_revert_attempted"] == 1
        assert row["auto_revert_succeeded"] == 1
        assert row["detail"] == "drop=0.20 >= floor 0.10"
    finally:
        await journal.stop()


# 5 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_decision_filter_by_proposal_id(tmp_path: Path):
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        for pid in ("p1", "p1", "p2"):
            await journal.record_optimization_decision(
                proposal_id=pid, decided_at=time.time(), decision="no_regression",
            )
        rows_p1 = await journal.get_recent_optimization_decisions(proposal_id="p1")
        rows_p2 = await journal.get_recent_optimization_decisions(proposal_id="p2")
        assert len(rows_p1) == 2
        assert len(rows_p2) == 1
    finally:
        await journal.stop()


# 6 ----------------------------------------------------------------------

def test_optimization_decision_frozen_and_to_dict():
    d = OptimizationDecision(
        proposal_id="x", decided_at=1.0, decision="regression",
        baseline_success_rate=0.8, post_success_rate=0.6, drop_amount=0.2,
        sample_count_baseline=30, sample_count_post=30,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        d.proposal_id = "y"  # type: ignore[misc]
    payload = d.to_dict()
    assert payload["proposal_id"] == "x"
    assert payload["decision"] == "regression"
    assert payload["sample_count_baseline"] == 30


# 7 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_success_rate_window_filters_by_time():
    now = 1000.0
    traces = [
        _trace(started_at=now - 1900, success=1),  # outside window (1800s)
        _trace(started_at=now - 100, success=1),
        _trace(started_at=now - 50, success=0),
        _trace(started_at=now - 25, success=1),
    ]
    journal = SimpleNamespace(
        get_recent_chain_traces=AsyncMock(return_value=traces),
    )
    runtime = SimpleNamespace(cognitive_journal=journal)
    counselor = OptimizationCounselor(runtime, observation_window_seconds=1800)
    rate, n = await counselor._compute_success_rate_window(
        end_time=now, window_seconds=1800.0,
    )
    assert n == 3  # the 1900s-old trace is excluded
    assert rate == pytest.approx(2 / 3)


# 8 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_skipped_when_insufficient_samples():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    runtime = SimpleNamespace(cognitive_journal=journal, emit_event=lambda *a, **k: None)
    counselor = OptimizationCounselor(runtime, min_samples_per_window=20)
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.9, baseline_n=5,
        post_rate=0.5, post_n=5,
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "skipped"
    assert kwargs["sample_count_baseline"] == 5


# 9 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_no_regression_when_drop_below_floor():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    captured: list = []
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        emit_event=lambda et, data: captured.append((et, data)),
    )
    counselor = OptimizationCounselor(
        runtime, min_samples_per_window=10, success_rate_drop_floor=0.10,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.85, baseline_n=30,
        post_rate=0.80, post_n=30,  # drop=0.05, below 0.10 floor
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "no_regression"
    assert captured == []  # no regression event emitted


# 10 ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_regression_no_revert_when_auto_revert_disabled():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    optimizer = MagicMock()
    optimizer.revert_proposal = AsyncMock()
    captured: list = []
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        chain_optimizer=optimizer,
        emit_event=lambda et, data: captured.append((et, data)),
    )
    counselor = OptimizationCounselor(
        runtime,
        min_samples_per_window=10,
        success_rate_drop_floor=0.10,
        auto_revert_enabled=False,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.90, baseline_n=30,
        post_rate=0.60, post_n=30,  # drop=0.30, well above floor
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "regression"
    assert kwargs["auto_revert_attempted"] is False
    optimizer.revert_proposal.assert_not_awaited()
    # Regression event emitted.
    assert any(
        et == EventType.OPTIMIZATION_REGRESSION_DETECTED for et, _ in captured
    )


# 11 ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_regression_and_reverts_when_auto_revert_enabled():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    optimizer = MagicMock()
    optimizer.revert_proposal = AsyncMock()
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        chain_optimizer=optimizer,
        emit_event=lambda *a, **k: None,
    )
    counselor = OptimizationCounselor(
        runtime,
        min_samples_per_window=10,
        success_rate_drop_floor=0.10,
        auto_revert_enabled=True,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.90, baseline_n=30,
        post_rate=0.60, post_n=30,
        decided_at=1.0,
    )
    optimizer.revert_proposal.assert_awaited_once_with(
        "p1", actor="optimization_counselor",
    )
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "regression"
    assert kwargs["auto_revert_attempted"] is True
    assert kwargs["auto_revert_succeeded"] is True


# 12 ---------------------------------------------------------------------

def test_chain_optimizer_counselor_config_defaults_and_validators():
    cfg = ChainOptimizerCounselorConfig()
    assert cfg.enabled is False
    assert cfg.auto_revert_enabled is False
    assert cfg.baseline_window_seconds == 1800.0
    assert cfg.observation_window_seconds == 1800.0
    assert cfg.success_rate_drop_floor == 0.10
    assert cfg.min_samples_per_window == 20
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(observation_window_seconds=0.0)
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(success_rate_drop_floor=1.5)
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(min_samples_per_window=0)
```

---

## What This Does NOT Change

- **`CounselorAgent` (`cognitive/counselor.py`) is untouched.** No new event handler added; AD-659c watchdog is its own service.
- **`ChainOptimizer.analyze` / `decide` / `_is_duplicate_pending`** unchanged.
- **`ChainTuningConfig`** unchanged.
- **`routers/chain_optimizer.py`** unchanged. No new REST endpoint for watchdog decisions in v1; `journal.get_recent_optimization_decisions()` is the read surface.
- **No HXI surface change.**
- **No `BridgeAlert` integration** (deferred AD-659c-1).
- **No new pool, no new agent, no new module beyond `cognitive/optimization_counselor.py`.**
- **Existing AD-659 + AD-659b tests** (`tests/test_ad659_chain_self_optimization.py`, `tests/test_ad659b_chain_optimizer_apply.py`) must continue to pass without modification — verified by Section 1 emissions being additive (events flow only when `emit_event` is wired; existing tests pass `emit_event=None`).

---

## Tracking

- **PROGRESS.md** — prepend AD-659c CLOSED entry.
- **`docs/development/roadmap.md`** — flip AD-659c status to ✅ shipped; add AD-659c-1 (p95 latency detection + bridge alert + statistical confidence intervals) and AD-659c-2 (HXI watchdog timeline) and AD-659c-3 (warm-boot replay of in-flight watchdog timers) as deferred follow-ups.
- **`DECISIONS.md`** — prepend AD-659c entry at top of Era V (per Wave 5 convention).

---

## Acceptance Criteria

1. All 12 new tests in `tests/test_ad659c_optimization_counselor.py` pass.
2. All existing AD-659 + AD-659b tests continue to pass without modification.
3. Full gate: **11220 passed** (Wave 52 baseline 11208 + 12 new = 11220 — exact target).
4. No new EventType collision (verified greenfield).
5. `ChainOptimizerCounselorConfig.enabled = False` by default — `runtime.optimization_counselor` is None when feature disabled. Boot with default config produces ZERO behavior change.
6. With `enabled=True` + `auto_revert_enabled=False`: watchdog observes + records decisions but never reverts (verified by Test #10).
7. With `enabled=True` + `auto_revert_enabled=True`: watchdog records + reverts on regression (verified by Test #11).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Out of Scope (Deferred — explicit forcing functions)

- **AD-659c-1**: p95 latency regression detection + Wilson-score statistical confidence + `BridgeAlert.deliver_bridge_alert` integration. Forcing function: AD-659c v1 ships and Captain validates success-rate detection accuracy in production.
- **AD-659c-2**: HXI watchdog timeline (Captain-facing visualization of applied/observed/reverted proposals). Forcing function: AD-659c-1 ships and decision-row volume is non-trivial.
- **AD-659c-3**: Warm-boot replay of in-flight watchdog timers (durable timer surface). Forcing function: ProbOS introduces a `runtime.timer_service` durable-timer protocol.
