# AD-635c — Clinical Telemetry v3: Circuit Breaker State History Persistence + Clinical Query

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-635 v1 + AD-635b (`ClinicalTelemetryService`, `audit_log` ring, `_record_audit`, `ClinicalAuditStore`; both COMPLETE), AD-488 / AD-506a / AD-506b (`CognitiveCircuitBreaker`, state + zone transitions; COMPLETE), AD-542 (`ConnectionFactory` pattern; COMPLETE).
**Estimated tests:** +14 (ceiling +18)
**Closes:** GH issue #392

## Problem

`src/probos/cognitive/circuit_breaker.py:54` declares `AgentBreakerState.zone_history` as a bounded `list[tuple[str, float]]` capped at 20 entries (line 412 truncates: `state.zone_history = state.zone_history[-20:]`). State transitions (`closed`↔`open`↔`half_open`) are **not persisted at all** — they only show up in `logger.info` lines and via the live `state.state` attribute. On restart, all trip history evaporates.

The clinical use-case from the roadmap (`docs/development/roadmap.md:5960`) is concrete: identifying agents with **recurring trips** as candidates for Counselor intervention or LIMDU. AD-635 v1's `query_dream_history` and `query_agent_chain_traces` cover dream cycles and chain traces. AD-635b persisted the audit ring. AD-635c closes the third deferred data domain — circuit-breaker state and zone transition history surfaced via `ClinicalTelemetryService` with a clearance-gated query method.

## Solution

Five additive edits + two new modules:

1. **`src/probos/config.py`** — extend `ClinicalTelemetryConfig` with two fields: `circuit_breaker_history_persistence_enabled: bool = False` and `circuit_breaker_history_db_path: str = "data/circuit_breaker_history.db"`. Update the docstring.
2. **`src/probos/cognitive/circuit_breaker_history_store.py` (NEW)** — `CircuitBreakerHistoryStore` class. SQLite-backed. Lazy connection via `_ensure_open()`. Optional `connection_factory` injection per AD-542. Public `async append(entry: dict) -> None` and `async recent(limit: int, *, agent_id: str | None = None) -> list[dict]`.
3. **`src/probos/cognitive/circuit_breaker.py`** — `__init__` accepts `history_store` keyword (default None); new `set_history_store(store)` setter; four hook insertions (in `_trip`, `should_allow_think`, `check_and_trip`, `_update_zone`) each calling a shared `_record_transition` helper that fires-and-forgets a SQLite write through `_schedule_history_write` / `_write_history` (mirrors AD-635b shape).
4. **`src/probos/cognitive/clinical_telemetry.py`** — `__init__` accepts `circuit_breaker_history_store` keyword (default None); new public `query_circuit_breaker_history(...)` clearance-gated method; updated module docstring.
5. **`src/probos/startup/finalize.py`** — extend `_wire_clinical_telemetry` to construct `CircuitBreakerHistoryStore` when both `cfg.enabled` AND `cfg.circuit_breaker_history_persistence_enabled` are True; pass it to `ClinicalTelemetryService` and stash it on `runtime.clinical_telemetry._pending_breaker_store`. Add a small late-bind block at the end of `finalize_startup` that consumes the pending store and attaches it to the breaker via `runtime.proactive_loop.circuit_breaker.set_history_store(...)` when both are present.
6. **`tests/test_ad635c_circuit_breaker_history.py` (NEW)** — 14 tests minimum.

No EventTypes added. No modification of `ClinicalTelemetryService.audit_log`, `_record_audit`, `query_dream_history`, `query_agent_chain_traces`, `ClinicalAuditStore`, `CognitiveCircuitBreaker.get_status`, `get_zone`, `get_all_statuses`, `get_last_zone_transition`, `record_event`, `reset_agent`, `reset_all`. No modification of `ProactiveCognitiveLoop` (the breaker setter is called from finalize, not the loop).

---

## Section 0 — `src/probos/config.py` (extend `ClinicalTelemetryConfig`)

**File:** `src/probos/config.py`

**SEARCH** (locks the entire `ClinicalTelemetryConfig` body verbatim — verified at HEAD lines 2027-2042):

```python
class ClinicalTelemetryConfig(BaseModel):
    """AD-635 / AD-635b: Clearance-gated clinical query facade (Medical / Counselor).

    AD-635 v1 shipped the read-only query facade with a bounded in-memory
    audit ring (``audit_max_entries`` deque). AD-635b adds optional
    SQLite persistence of the audit ring for post-incident review,
    gated by ``audit_persistence_enabled`` (default False per Wave-10
    convention #14 — transitional flag, default off until validated).

    The service is invisible at runtime out-of-the-box (``enabled=False``).
    Captain opts in via YAML; persistence requires a second opt-in.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
    audit_persistence_enabled: bool = False
    audit_db_path: str = "data/clinical_audit.db"
```

**REPLACE** (re-emits the class + extended docstring + 2 new fields after the existing four):

```python
class ClinicalTelemetryConfig(BaseModel):
    """AD-635 / AD-635b / AD-635c: Clearance-gated clinical query facade (Medical / Counselor).

    AD-635 v1 shipped the read-only query facade with a bounded in-memory
    audit ring (``audit_max_entries`` deque). AD-635b adds optional
    SQLite persistence of the audit ring for post-incident review,
    gated by ``audit_persistence_enabled``. AD-635c adds optional
    SQLite persistence of cognitive-circuit-breaker state and zone
    transitions, gated by ``circuit_breaker_history_persistence_enabled``,
    plus a clearance-gated ``query_circuit_breaker_history`` method on
    ``ClinicalTelemetryService`` that reads from the durable store.

    Each persistence flag defaults False per Wave-10 convention #14
    (transitional flag, default off until validated). The service is
    invisible at runtime out-of-the-box (``enabled=False``). Captain
    opts in via YAML; each persistence side requires its own opt-in.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
    audit_persistence_enabled: bool = False
    audit_db_path: str = "data/clinical_audit.db"
    circuit_breaker_history_persistence_enabled: bool = False
    circuit_breaker_history_db_path: str = "data/circuit_breaker_history.db"
```

---

## Section 1 — `src/probos/cognitive/circuit_breaker_history_store.py` (NEW file)

**File:** `src/probos/cognitive/circuit_breaker_history_store.py`

Create the file with this exact content:

```python
"""AD-635c: CircuitBreakerHistoryStore — SQLite-backed durable store for
cognitive circuit-breaker state and zone transitions.

Mirrors the AD-635b / AD-542 ConnectionFactory pattern (cf.
``clinical_audit_store.py`` and ``activation_tracker.py``): constructor
accepts an optional callable returning an aiosqlite-compatible
connection; default uses ``aiosqlite.connect(db_path)`` directly.
Commercial overlays inject a Postgres / cloud factory without changing
call sites (AD-635c-5 deferral target).

Lifecycle:

  * ``__init__`` is sync and does NOT touch disk. The SQLite file is
    created on first ``append(...)`` via ``_ensure_open()``.
  * No explicit ``close()`` in v1 — Python GC closes file handles on
    process exit. Explicit close is part of AD-635c-1 (restore-on-boot).

Schema (v1):

  CREATE TABLE circuit_breaker_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      agent_id TEXT NOT NULL,
      transition_kind TEXT NOT NULL,    -- "state" or "zone"
      old_value TEXT NOT NULL,          -- e.g. "closed", "green"
      new_value TEXT NOT NULL,          -- e.g. "open", "amber"
      trip_count INTEGER NOT NULL DEFAULT 0,
      cooldown_seconds REAL NOT NULL DEFAULT 0.0,
      reason TEXT
  );
  CREATE INDEX idx_cbh_ts ON circuit_breaker_history(ts DESC);
  CREATE INDEX idx_cbh_agent_ts ON circuit_breaker_history(agent_id, ts DESC);
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS circuit_breaker_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    agent_id TEXT NOT NULL,
    transition_kind TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    trip_count INTEGER NOT NULL DEFAULT 0,
    cooldown_seconds REAL NOT NULL DEFAULT 0.0,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_cbh_ts ON circuit_breaker_history(ts DESC);
CREATE INDEX IF NOT EXISTS idx_cbh_agent_ts ON circuit_breaker_history(agent_id, ts DESC);
"""


class CircuitBreakerHistoryStore:
    """AD-635c: SQLite-backed history store for CognitiveCircuitBreaker."""

    def __init__(
        self,
        *,
        db_path: str,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def append(self, entry: dict[str, Any]) -> None:
        """Persist one transition row.

        ``entry`` must contain ``ts``, ``agent_id``, ``transition_kind``,
        ``old_value``, ``new_value``. Optional: ``trip_count`` (default 0),
        ``cooldown_seconds`` (default 0.0), ``reason`` (default None).
        """
        await self._ensure_open()
        await self._db.execute(
            "INSERT INTO circuit_breaker_history "
            "(ts, agent_id, transition_kind, old_value, new_value, "
            "trip_count, cooldown_seconds, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                float(entry["ts"]),
                str(entry["agent_id"]),
                str(entry["transition_kind"]),
                str(entry["old_value"]),
                str(entry["new_value"]),
                int(entry.get("trip_count", 0)),
                float(entry.get("cooldown_seconds", 0.0)),
                entry.get("reason"),
            ),
        )
        await self._db.commit()

    async def recent(
        self,
        limit: int,
        *,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most-recent rows (highest ``ts`` first).

        When ``agent_id`` is provided, filters by agent_id (uses the
        composite ``idx_cbh_agent_ts`` index). When None, returns rows
        across all agents (uses the ``idx_cbh_ts`` index).
        """
        if limit <= 0:
            return []
        await self._ensure_open()
        if agent_id is not None:
            cursor = await self._db.execute(
                "SELECT ts, agent_id, transition_kind, old_value, new_value, "
                "trip_count, cooldown_seconds, reason FROM circuit_breaker_history "
                "WHERE agent_id = ? ORDER BY ts DESC LIMIT ?",
                (str(agent_id), int(limit)),
            )
        else:
            cursor = await self._db.execute(
                "SELECT ts, agent_id, transition_kind, old_value, new_value, "
                "trip_count, cooldown_seconds, reason FROM circuit_breaker_history "
                "ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            )
        rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "ts": row[0],
                "agent_id": row[1],
                "transition_kind": row[2],
                "old_value": row[3],
                "new_value": row[4],
                "trip_count": row[5],
                "cooldown_seconds": row[6],
            }
            if row[7] is not None:
                entry["reason"] = row[7]
            result.append(entry)
        return result

    async def _ensure_open(self) -> None:
        """Lazy SQLite open + schema bootstrap. Idempotent."""
        if self._db is not None:
            return
        if self._connection_factory is not None:
            self._db = await self._connection_factory()
        else:
            import aiosqlite
            self._db = await aiosqlite.connect(self._db_path)
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()
```

---

## Section 2 — `src/probos/cognitive/circuit_breaker.py` (extend)

**File:** `src/probos/cognitive/circuit_breaker.py`

### Section 2a — extend module docstring + imports

**SEARCH** (locks docstring + imports verbatim — verified at HEAD lines 1-21):

```python
"""AD-488: Cognitive Circuit Breaker — metacognitive loop detection.

Monitors per-agent cognitive event patterns for rumination signatures
and intervenes with forced cooldown + attention redirection.
Not punishment — health protection.

AD-506a: Graduated 4-zone model (Green → Amber → Red → Critical).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.cognitive.similarity import jaccard_similarity

logger = logging.getLogger(__name__)
```

**REPLACE** (extends docstring; adds `asyncio` import; adds `TYPE_CHECKING` block for forward-ref):

```python
"""AD-488 / AD-635c: Cognitive Circuit Breaker — metacognitive loop detection.

Monitors per-agent cognitive event patterns for rumination signatures
and intervenes with forced cooldown + attention redirection.
Not punishment — health protection.

AD-506a: Graduated 4-zone model (Green → Amber → Red → Critical).
AD-635c: Optional SQLite write-through persistence of state + zone
transitions via ``CircuitBreakerHistoryStore``. Default-off; opt-in via
``ClinicalTelemetryConfig.circuit_breaker_history_persistence_enabled``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from probos.cognitive.similarity import jaccard_similarity

if TYPE_CHECKING:
    # AD-635c: forward-ref to avoid a runtime import cycle with the
    # history-store module (defense in depth — current shape has no cycle).
    from probos.cognitive.circuit_breaker_history_store import (
        CircuitBreakerHistoryStore,
    )

logger = logging.getLogger(__name__)
```

### Section 2b — extend `__init__` (accept optional `history_store` + tracking set)

**SEARCH** (locks the END of the `__init__` body verbatim — verified at HEAD lines 191-194):

```python
        self._agents: dict[str, AgentBreakerState] = {}
        self._trip_reasons: dict[str, str] = {}  # AD-495: per-agent trip reason
        self._trait_thresholds: dict[str, TraitAdaptiveThresholds] = {}  # AD-494
```

**REPLACE** (re-emits the three lines verbatim; appends the AD-635c instance attrs):

```python
        self._agents: dict[str, AgentBreakerState] = {}
        self._trip_reasons: dict[str, str] = {}  # AD-495: per-agent trip reason
        self._trait_thresholds: dict[str, TraitAdaptiveThresholds] = {}  # AD-494
        # AD-635c: optional SQLite write-through. None preserves AD-488 +
        # AD-506a behavior bit-for-bit. Tasks tracked per the Standing Order
        # on async hygiene (fire-and-forget references held).
        self._history_store: "CircuitBreakerHistoryStore | None" = None
        self._write_tasks: set[asyncio.Task[None]] = set()
```

### Section 2c — late-bind setter `set_history_store`

**SEARCH** (locks the existing `_get_state` method verbatim — verified at HEAD lines 196-200):

```python
    def _get_state(self, agent_id: str) -> AgentBreakerState:
        """Get or create per-agent breaker state."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentBreakerState()
        return self._agents[agent_id]
```

**REPLACE** (re-emits `_get_state` verbatim; appends the public setter):

```python
    def _get_state(self, agent_id: str) -> AgentBreakerState:
        """Get or create per-agent breaker state."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentBreakerState()
        return self._agents[agent_id]

    def set_history_store(
        self, store: "CircuitBreakerHistoryStore | None"
    ) -> None:
        """AD-635c: late-bind seam — attach a history store after construction.

        Called from ``startup/finalize.py`` once both the proactive loop
        (which owns the breaker) and the clinical-telemetry wirer (which
        owns the config) have completed their primary wiring. Passing
        ``None`` clears the seam.
        """
        self._history_store = store
```

### Section 2d — hook in `should_allow_think` (OPEN → HALF_OPEN)

**SEARCH** (locks the OPEN-branch transition body verbatim — verified at HEAD lines 286-294):

```python
        if state.state == BreakerState.OPEN:
            # Check if cooldown has elapsed → transition to HALF_OPEN
            elapsed = now - state.tripped_at
            if elapsed >= state.cooldown_seconds:
                state.state = BreakerState.HALF_OPEN
                state.last_probe_at = now
                logger.info(
                    "AD-488: Circuit breaker HALF_OPEN for %s (cooldown %.0fs elapsed)",
                    agent_id, elapsed,
                )
                return True  # Allow one probe think
```

**REPLACE** (inserts the AD-635c hook BEFORE the `logger.info` call but AFTER the state mutation — DLog #2 ordering):

```python
        if state.state == BreakerState.OPEN:
            # Check if cooldown has elapsed → transition to HALF_OPEN
            elapsed = now - state.tripped_at
            if elapsed >= state.cooldown_seconds:
                state.state = BreakerState.HALF_OPEN
                state.last_probe_at = now
                # AD-635c: record state transition (open → half_open).
                self._record_transition(
                    agent_id,
                    transition_kind="state",
                    old_value="open",
                    new_value="half_open",
                    trip_count=state.trip_count,
                    cooldown_seconds=state.cooldown_seconds,
                )
                logger.info(
                    "AD-488: Circuit breaker HALF_OPEN for %s (cooldown %.0fs elapsed)",
                    agent_id, elapsed,
                )
                return True  # Allow one probe think
```

### Section 2e — hook in `check_and_trip` (HALF_OPEN → CLOSED recovery)

**SEARCH** (locks the recovery branch verbatim — verified at HEAD lines 469-472):

```python
        # If HALF_OPEN and no signals → recovery successful → CLOSED
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            logger.info("AD-488: Circuit breaker CLOSED for %s (recovery confirmed)", agent_id)
```

**REPLACE** (inserts hook AFTER state mutation, BEFORE logger.info):

```python
        # If HALF_OPEN and no signals → recovery successful → CLOSED
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            # AD-635c: record state transition (half_open → closed).
            self._record_transition(
                agent_id,
                transition_kind="state",
                old_value="half_open",
                new_value="closed",
                trip_count=state.trip_count,
                cooldown_seconds=state.cooldown_seconds,
            )
            logger.info("AD-488: Circuit breaker CLOSED for %s (recovery confirmed)", agent_id)
```

### Section 2f — hook in `_trip` (CLOSED|HALF_OPEN → OPEN)

**SEARCH** (locks the entire `_trip` body verbatim — verified at HEAD lines 479-499):

```python
    def _trip(self, agent_id: str, reason: str) -> None:
        """Trip the circuit breaker for an agent."""
        state = self._get_state(agent_id)
        state.trip_count += 1
        state.tripped_at = time.monotonic()
        state.state = BreakerState.OPEN

        # Escalating cooldown: base × 2^(trip_count - 1), capped
        # AD-494: Use trait-adapted base cooldown
        eff = self._effective_thresholds(agent_id)
        cooldown = min(
            eff["base_cooldown"] * (2 ** (state.trip_count - 1)),
            self._max_cooldown,
        )
        state.cooldown_seconds = cooldown

        logger.warning(
            "AD-488: Circuit breaker TRIPPED for %s — %s. "
            "Cooldown: %.0fs. Trip count: %d",
            agent_id, reason, cooldown, state.trip_count,
        )
```

**REPLACE** (captures prior state value FIRST, mutates, computes cooldown, hooks BEFORE warning):

```python
    def _trip(self, agent_id: str, reason: str) -> None:
        """Trip the circuit breaker for an agent."""
        state = self._get_state(agent_id)
        # AD-635c: capture the prior state value BEFORE mutation, so the
        # transition row carries closed→open or half_open→open correctly.
        prior_state_value = state.state.value
        state.trip_count += 1
        state.tripped_at = time.monotonic()
        state.state = BreakerState.OPEN

        # Escalating cooldown: base × 2^(trip_count - 1), capped
        # AD-494: Use trait-adapted base cooldown
        eff = self._effective_thresholds(agent_id)
        cooldown = min(
            eff["base_cooldown"] * (2 ** (state.trip_count - 1)),
            self._max_cooldown,
        )
        state.cooldown_seconds = cooldown

        # AD-635c: record state transition (closed|half_open → open).
        self._record_transition(
            agent_id,
            transition_kind="state",
            old_value=prior_state_value,
            new_value="open",
            trip_count=state.trip_count,
            cooldown_seconds=state.cooldown_seconds,
            reason=reason,
        )

        logger.warning(
            "AD-488: Circuit breaker TRIPPED for %s — %s. "
            "Cooldown: %.0fs. Trip count: %d",
            agent_id, reason, cooldown, state.trip_count,
        )
```

### Section 2g — hook in `_update_zone` (zone change)

**SEARCH** (locks the existing zone-changed branch verbatim — verified at HEAD lines 421-435):

```python
        if new_zone != old_zone:
            state.zone = new_zone
            state.zone_entered_at = now
            state.zone_history.append((new_zone.value, now))
            # Cap zone_history at 20 entries
            if len(state.zone_history) > 20:
                state.zone_history = state.zone_history[-20:]
            # AD-506b: Cache transition for recovery detection
            state.last_zone_transition = (old_zone.value, new_zone.value)
            logger.info(
                "AD-506a: Zone transition %s -> %s for %s",
                old_zone.value, new_zone.value, agent_id,
            )
        else:
            state.last_zone_transition = None
```

**REPLACE** (inserts hook AFTER the in-memory zone_history append/cap and AFTER `last_zone_transition` assignment, BEFORE `logger.info`):

```python
        if new_zone != old_zone:
            state.zone = new_zone
            state.zone_entered_at = now
            state.zone_history.append((new_zone.value, now))
            # Cap zone_history at 20 entries
            if len(state.zone_history) > 20:
                state.zone_history = state.zone_history[-20:]
            # AD-506b: Cache transition for recovery detection
            state.last_zone_transition = (old_zone.value, new_zone.value)
            # AD-635c: record zone transition (green|amber|red|critical).
            self._record_transition(
                agent_id,
                transition_kind="zone",
                old_value=old_zone.value,
                new_value=new_zone.value,
                trip_count=state.trip_count,
            )
            logger.info(
                "AD-506a: Zone transition %s -> %s for %s",
                old_zone.value, new_zone.value, agent_id,
            )
        else:
            state.last_zone_transition = None
```

### Section 2h — append `_record_transition` + `_schedule_history_write` + `_write_history`

These three private helpers are appended to the END of `CognitiveCircuitBreaker`. The current last method on the class at HEAD is `reset_all` (line 562); the SEARCH locks `reset_all`'s body verbatim, the REPLACE re-emits it, and appends the three helpers as the new tail.

**SEARCH** (locks the entire `reset_all` body verbatim — verified at HEAD lines 558-562):

```python
    def reset_all(self) -> None:
        """Reset all breaker states."""
        self._agents.clear()
        self._trip_reasons.clear()
        self._trait_thresholds.clear()  # AD-494
```

**REPLACE** (re-emits `reset_all` verbatim; appends the three AD-635c helpers):

```python
    def reset_all(self) -> None:
        """Reset all breaker states."""
        self._agents.clear()
        self._trip_reasons.clear()
        self._trait_thresholds.clear()  # AD-494

    # ---- AD-635c: history write-through ---------------------------------

    def _record_transition(
        self,
        agent_id: str,
        *,
        transition_kind: str,
        old_value: str,
        new_value: str,
        trip_count: int = 0,
        cooldown_seconds: float = 0.0,
        reason: str | None = None,
    ) -> None:
        """AD-635c: record one state or zone transition.

        Short-circuits when no history store is attached — keeps the
        no-persistence path free of any per-call overhead beyond a single
        attribute load + None check.
        """
        if self._history_store is None:
            return
        entry: dict[str, Any] = {
            "ts": time.time(),
            "agent_id": agent_id,
            "transition_kind": transition_kind,
            "old_value": old_value,
            "new_value": new_value,
            "trip_count": int(trip_count),
            "cooldown_seconds": float(cooldown_seconds),
        }
        if reason is not None:
            entry["reason"] = reason
        self._schedule_history_write(entry)

    def _schedule_history_write(self, entry: dict[str, Any]) -> None:
        """AD-635c: fire-and-forget SQLite persistence task."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-635c: no running event loop; circuit-breaker history "
                "write skipped",
            )
            return
        task = loop.create_task(self._write_history(entry))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    async def _write_history(self, entry: dict[str, Any]) -> None:
        """AD-635c: persist one transition entry; tier-2 log-and-degrade."""
        try:
            await self._history_store.append(entry)
        except Exception:
            logger.warning(
                "AD-635c: circuit-breaker history write-through failed for "
                "%s/%s (%s -> %s)",
                entry.get("agent_id"),
                entry.get("transition_kind"),
                entry.get("old_value"),
                entry.get("new_value"),
                exc_info=True,
            )
```

---

## Section 3 — `src/probos/cognitive/clinical_telemetry.py` (extend)

**File:** `src/probos/cognitive/clinical_telemetry.py`

### Section 3a — extend module docstring + TYPE_CHECKING

**SEARCH** (locks the module docstring + imports verbatim — verified at HEAD lines 1-43):

```python
"""AD-635 / AD-635b — Clinical Telemetry Query Facade.

Clearance-gated read-only query service enabling Medical (Chapel,
chief_medical/FULL) and Counselor (Echo, counselor/ORACLE) to perform
cross-agent clinical diagnostics over substrate telemetry.

v1 surfaces TWO data domains:
  - Dream cycle history (via EmergentDetector.recent_dreams)
  - Cross-agent cognitive journal chain traces (via CognitiveJournal.get_recent_chain_traces)

Circuit breaker state history is deferred to AD-635c.
REST endpoints, shell command, and proactive injection are deferred to AD-635d/e/f.

AD-635b adds optional SQLite write-through persistence of the audit ring
via ``ClinicalAuditStore``. Default-off; opt-in via ``audit_persistence_enabled``.

Authorization model (AD-620/622): caller must hold a clearance tier of FULL
or ORACLE (resolved via effective_recall_tier from rank + billet + active
grants) AND have a clinical agent_type. Denied queries return [] and log
a warning — they never raise. Every query is logged to a bounded in-memory
audit ring (and durably to SQLite when persistence is enabled).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.earned_agency import (
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
    resolve_billet_clearance,
)

if TYPE_CHECKING:
    # AD-635b: forward-ref to avoid a runtime import cycle with the
    # audit-store module (defense in depth — current shape has no cycle).
    from probos.cognitive.clinical_audit_store import ClinicalAuditStore

logger = logging.getLogger(__name__)
```

**REPLACE** (extends docstring; adds the AD-635c forward-ref):

```python
"""AD-635 / AD-635b / AD-635c — Clinical Telemetry Query Facade.

Clearance-gated read-only query service enabling Medical (Chapel,
chief_medical/FULL) and Counselor (Echo, counselor/ORACLE) to perform
cross-agent clinical diagnostics over substrate telemetry.

v3 surfaces THREE data domains:
  - Dream cycle history (via EmergentDetector.recent_dreams; AD-635 v1)
  - Cross-agent cognitive journal chain traces (via CognitiveJournal.get_recent_chain_traces; AD-635 v1)
  - Cognitive circuit breaker state + zone transition history (via CircuitBreakerHistoryStore; AD-635c)

REST endpoints, shell command, and proactive injection are deferred to AD-635d/e/f.

AD-635b adds optional SQLite write-through persistence of the audit ring
via ``ClinicalAuditStore``. AD-635c adds optional SQLite write-through
persistence of cognitive-circuit-breaker transitions via
``CircuitBreakerHistoryStore`` plus the clearance-gated
``query_circuit_breaker_history`` reader. Both are default-off; opt-in
via ``audit_persistence_enabled`` and
``circuit_breaker_history_persistence_enabled`` respectively.

Authorization model (AD-620/622): caller must hold a clearance tier of FULL
or ORACLE (resolved via effective_recall_tier from rank + billet + active
grants) AND have a clinical agent_type. Denied queries return [] and log
a warning — they never raise. Every query is logged to a bounded in-memory
audit ring (and durably to SQLite when persistence is enabled).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.earned_agency import (
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
    resolve_billet_clearance,
)

if TYPE_CHECKING:
    # AD-635b / AD-635c: forward-refs to avoid runtime import cycles
    # with the persistence modules (defense in depth — current shapes
    # have no cycle).
    from probos.cognitive.clinical_audit_store import ClinicalAuditStore
    from probos.cognitive.circuit_breaker_history_store import (
        CircuitBreakerHistoryStore,
    )

logger = logging.getLogger(__name__)
```

### Section 3b — extend `__init__`

**SEARCH** (locks the entire ctor body verbatim — verified at HEAD lines 60-77):

```python
    def __init__(
        self,
        runtime: Any,
        *,
        audit_max_entries: int = 1000,
        audit_store: "ClinicalAuditStore | None" = None,
    ) -> None:
        self._runtime = runtime
        self._audit: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=max(1, int(audit_max_entries))
        )
        # AD-635b: optional SQLite write-through. None preserves AD-635 v1
        # in-memory-only behavior bit-for-bit. Tasks are tracked per the
        # Standing Order on async hygiene (fire-and-forget references held).
        self._audit_store = audit_store
        self._write_tasks: set[asyncio.Task[None]] = set()
```

**REPLACE** (adds the new keyword + instance attr; existing fields unchanged):

```python
    def __init__(
        self,
        runtime: Any,
        *,
        audit_max_entries: int = 1000,
        audit_store: "ClinicalAuditStore | None" = None,
        circuit_breaker_history_store: "CircuitBreakerHistoryStore | None" = None,
    ) -> None:
        self._runtime = runtime
        self._audit: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=max(1, int(audit_max_entries))
        )
        # AD-635b: optional SQLite write-through. None preserves AD-635 v1
        # in-memory-only behavior bit-for-bit. Tasks are tracked per the
        # Standing Order on async hygiene (fire-and-forget references held).
        self._audit_store = audit_store
        self._write_tasks: set[asyncio.Task[None]] = set()
        # AD-635c: optional CircuitBreakerHistoryStore handle for the
        # query_circuit_breaker_history reader. None disables the third
        # data domain (returns [] like the other domains do when their
        # underlying store is unavailable).
        self._circuit_breaker_history_store = circuit_breaker_history_store
```

### Section 3c — append `query_circuit_breaker_history` method

**SEARCH** (locks the existing `audit_log` property verbatim — verified at HEAD lines 198-201):

```python
    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Snapshot of the audit ring (most recent last). Returns a copy."""
        return list(self._audit)
```

**REPLACE** (re-emits the property verbatim; appends the new public method):

```python
    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Snapshot of the audit ring (most recent last). Returns a copy."""
        return list(self._audit)

    async def query_circuit_breaker_history(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """AD-635c: Return up to `limit` recent breaker transitions.

        When `target_agent_id` is provided, filters to that agent.
        When None, returns transitions across all agents (most recent
        first). Returns [] (not raises) if requester lacks clearance,
        if the store is unavailable, or on any underlying failure.
        Every call is logged to the audit ring.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=False,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            logger.warning(
                "AD-635c: circuit_breaker_history denied for %s "
                "(clearance/role gate)",
                requester_agent_id,
            )
            return []

        store = self._circuit_breaker_history_store
        if store is None:
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        try:
            rows = await store.recent(
                max(0, int(limit)),
                agent_id=target_agent_id,
            )
        except Exception:
            logger.warning(
                "AD-635c: circuit_breaker_history query failed for %s -> %s",
                requester_agent_id, target_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        self._record_audit(
            requester_agent_id,
            "circuit_breaker_history",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
        )
        return rows
```

---

## Section 4 — `src/probos/startup/finalize.py` (extend `_wire_clinical_telemetry` + late-bind block)

**File:** `src/probos/startup/finalize.py`

### Section 4a — extend `_wire_clinical_telemetry`

**SEARCH** (locks the entire current wirer body verbatim — verified at HEAD lines 550-583):

```python
def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 / AD-635b: Wire ClinicalTelemetryService + optional audit persistence."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    audit_store = None
    if cfg.audit_persistence_enabled:
        # AD-635b: double-gated — service must be enabled AND persistence
        # opted in. Default cfg.audit_persistence_enabled=False keeps the
        # AD-635 v1 in-memory-only contract.
        from probos.cognitive.clinical_audit_store import ClinicalAuditStore
        audit_store = ClinicalAuditStore(db_path=cfg.audit_db_path)
        logger.info(
            "AD-635b: ClinicalAuditStore wired (db_path=%s)",
            cfg.audit_db_path,
        )

    runtime.clinical_telemetry = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
        audit_store=audit_store,
    )
    logger.info(
        "AD-635: ClinicalTelemetryService v1 initialized "
        "(2 domains: dream_history + chain_traces; clearance gate FULL+; "
        "persistence=%s)",
        bool(audit_store),
    )
    return True
```

**REPLACE** (re-emits the wirer; extends with double-gated `CircuitBreakerHistoryStore` construction; pending-store stash for late-bind):

```python
def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 / AD-635b / AD-635c: Wire ClinicalTelemetryService +
    optional audit persistence + optional circuit-breaker history persistence."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    audit_store = None
    if cfg.audit_persistence_enabled:
        # AD-635b: double-gated — service must be enabled AND persistence
        # opted in. Default cfg.audit_persistence_enabled=False keeps the
        # AD-635 v1 in-memory-only contract.
        from probos.cognitive.clinical_audit_store import ClinicalAuditStore
        audit_store = ClinicalAuditStore(db_path=cfg.audit_db_path)
        logger.info(
            "AD-635b: ClinicalAuditStore wired (db_path=%s)",
            cfg.audit_db_path,
        )

    breaker_history_store = None
    if cfg.circuit_breaker_history_persistence_enabled:
        # AD-635c: double-gated — service must be enabled AND breaker-
        # history persistence opted in. Default disabled flag keeps the
        # AD-488 / AD-506a in-memory-only contract.
        from probos.cognitive.circuit_breaker_history_store import (
            CircuitBreakerHistoryStore,
        )
        breaker_history_store = CircuitBreakerHistoryStore(
            db_path=cfg.circuit_breaker_history_db_path,
        )
        logger.info(
            "AD-635c: CircuitBreakerHistoryStore wired (db_path=%s)",
            cfg.circuit_breaker_history_db_path,
        )

    service = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
        audit_store=audit_store,
        circuit_breaker_history_store=breaker_history_store,
    )
    # AD-635c: stash the breaker store for the late-bind block at the
    # tail of finalize_startup. The proactive-loop wirer runs AFTER us;
    # the late-bind reads this attribute and calls
    # ``runtime.proactive_loop.circuit_breaker.set_history_store(...)``.
    service._pending_breaker_store = breaker_history_store
    runtime.clinical_telemetry = service
    logger.info(
        "AD-635: ClinicalTelemetryService initialized "
        "(3 domains: dream_history + chain_traces + circuit_breaker_history; "
        "clearance gate FULL+; audit_persistence=%s; breaker_history_persistence=%s)",
        bool(audit_store), bool(breaker_history_store),
    )
    return True
```

### Section 4b — late-bind block inside the proactive-cognitive-loop wirer

**Goal:** attach the pending breaker store to the breaker after the proactive loop's `set_config(...)` constructs it (which is where the breaker is re-instantiated with `cb_config=config.circuit_breaker`).

**Critical correctness note (pass-1 finding):** `runtime.proactive_loop` is NOT yet assigned during `finalize_startup` — the runtime's main loop assigns `self.proactive_loop = fin.proactive_loop` AFTER `finalize_startup` returns (verified at `runtime.py:1704`). Therefore the late-bind block must use the **local `proactive_loop` variable** inside the proactive block of `finalize_startup`, not `runtime.proactive_loop`. Clinical wiring runs first (line 935); when control reaches the proactive block (line 985+), `runtime.clinical_telemetry` is already populated and `_pending_breaker_store` is already stashed (or None).

**SEARCH** (locks the existing line that completes breaker construction via `set_config` — verified at HEAD line 1006):

```python
        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)
```

**REPLACE** (re-emits the line verbatim; appends the AD-635c late-bind block immediately after — at this point `proactive_loop.circuit_breaker` is the freshly constructed breaker that should receive the store):

```python
        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)
        # AD-635c: late-bind seam — attach the CircuitBreakerHistoryStore
        # (constructed by _wire_clinical_telemetry above) to the breaker
        # owned by the proactive loop. Either side missing — clinical
        # disabled, persistence disabled, or no pending store — is
        # silently fine; the breaker simply stays unattached and
        # query_circuit_breaker_history returns [] from an empty store.
        _clinical = getattr(runtime, "clinical_telemetry", None)
        if _clinical is not None:
            _pending_store = getattr(_clinical, "_pending_breaker_store", None)
            if _pending_store is not None:
                try:
                    proactive_loop.circuit_breaker.set_history_store(_pending_store)
                    logger.info(
                        "AD-635c: CircuitBreakerHistoryStore attached to "
                        "CognitiveCircuitBreaker via late-bind"
                    )
                except Exception:
                    logger.warning(
                        "AD-635c: failed to attach CircuitBreakerHistoryStore "
                        "to breaker via late-bind",
                        exc_info=True,
                    )
```

The `try/except` is tier-2 log-and-degrade — if the attach fails for any reason, finalize continues; the breaker simply doesn't get the store. The block runs only when `config.proactive_cognitive.enabled and runtime.ward_room` is True (the enclosing `if` at line 981); when proactive cognitive is disabled, no late-bind happens, the pending store on the clinical service is harmless dead state, and `query_circuit_breaker_history` reads from an empty (but valid) durable store directly.

---

## Section 5 — `tests/test_ad635c_circuit_breaker_history.py` (NEW file)

**File:** `tests/test_ad635c_circuit_breaker_history.py`

Create the file. Target 14 tests minimum (ceiling 18). Required test names + behaviors:

**Config + store basics (tests 1-3):**

1. `test_clinical_telemetry_config_breaker_history_default_false` — `ClinicalTelemetryConfig().circuit_breaker_history_persistence_enabled is False`.
2. `test_clinical_telemetry_config_breaker_history_db_path_default` — `ClinicalTelemetryConfig().circuit_breaker_history_db_path == "data/circuit_breaker_history.db"`.
3. `test_circuit_breaker_history_store_constructor_does_not_touch_disk` — construct with `db_path=str(tmp_path / "x.db")`; assert `os.path.exists(...)` is False; assert `store.is_open is False`.

**Store CRUD (tests 4-6):**

4. `test_circuit_breaker_history_store_append_creates_file_lazily` — construct + `await store.append({...})`; assert file exists; `store.is_open is True`. Use `asyncio.run(...)`.
5. `test_circuit_breaker_history_store_append_persists_state_and_zone_rows` — append one `transition_kind="state"` entry and one `transition_kind="zone"` entry; `await store.recent(10)` returns both rows in DESC ts order, with the correct `transition_kind`, `old_value`, `new_value`, `trip_count`, `cooldown_seconds`, and `reason` fields.
6. `test_circuit_breaker_history_store_recent_zero_returns_empty` — `await store.recent(0) == []` and `await store.recent(0, agent_id="x") == []` even with rows present.

**Breaker hooks (tests 7-11):**

7. `test_breaker_trip_records_state_transition_with_reason` — construct breaker with `history_store = AsyncMock()`-backed via `set_history_store(...)`; `breaker._trip("agent-1", "rumination")` from the default CLOSED state; await `breaker._write_tasks`; assert one `append` call with entry `{transition_kind: "state", old_value: "closed", new_value: "open", trip_count: 1, reason: "rumination", cooldown_seconds: > 0}`.
8. `test_breaker_trip_after_half_open_records_half_open_to_open` — pre-set `breaker._get_state("agent-1").state = BreakerState.HALF_OPEN`; call `_trip`; assert one append with `old_value="half_open", new_value="open"`.
9. `test_breaker_should_allow_think_records_open_to_half_open_on_cooldown_elapse` — pre-set state to OPEN with `tripped_at=time.monotonic() - 100000` (cooldown elapsed); call `should_allow_think("agent-1")` returning True; await tasks; assert append with `transition_kind="state", old_value="open", new_value="half_open"`.
10. `test_breaker_check_and_trip_records_half_open_to_closed_on_recovery` — pre-set state to HALF_OPEN with no recent events (so signals don't fire); call `check_and_trip("agent-1")`; assert append with `transition_kind="state", old_value="half_open", new_value="closed"`.
11. `test_breaker_update_zone_records_zone_transitions` — drive a sequence that crosses GREEN→AMBER (e.g. record several similar events to push `similarity_ratio` above amber threshold, call `_compute_signals`, call `_update_zone(agent_id, signals, tripped=False)`); await tasks; assert the most recent `transition_kind="zone"` row has `old_value="green", new_value="amber"`.

**Failure + no-loop semantics (tests 12-13):**

12. `test_breaker_history_write_failure_does_not_block_state_transition` — `history_store.append` raises `RuntimeError("disk full")`; call `_trip`; await tasks via `asyncio.gather(*breaker._write_tasks, return_exceptions=True)`; assert WARNING captured (`"AD-635c: circuit-breaker history write-through failed"`); assert `breaker._get_state("agent-1").state == BreakerState.OPEN` (state mutation succeeded); assert the call did NOT raise.
13. `test_breaker_history_no_running_loop_skips_write_silently` — call `_trip` from a sync test (no event loop); assert NO exception; assert `len(breaker._write_tasks) == 0`; (optionally assert DEBUG log captured if caplog is at DEBUG level).

**Clinical query method (tests 14-17):**

14. `test_query_circuit_breaker_history_denied_for_non_clinical_role` — minimal `_make_runtime(...)` with `agents={"engineer-1": "engineer"}`; service with `circuit_breaker_history_store = AsyncMock()`; `await svc.query_circuit_breaker_history(requester_agent_id="engineer-1")` returns `[]`; audit-ring entry has `granted=False, query_type="circuit_breaker_history"`.
15. `test_query_circuit_breaker_history_returns_rows_for_clinical_role` — runtime with `agents={"echo-1": "counselor"}` (ORACLE clearance via the existing AD-635 test fixture pattern); store mock returns `[{"transition_kind": "state", ...}]` from `recent(...)`; `await svc.query_circuit_breaker_history(requester_agent_id="echo-1", target_agent_id="khan-1", limit=10)` returns the rows; audit-ring entry has `granted=True, target_agent_id="khan-1"`; `store.recent` was called with `(10, agent_id="khan-1")`.
16. `test_query_circuit_breaker_history_returns_empty_when_store_is_none` — service with `circuit_breaker_history_store=None`; clinical role; `await svc.query_circuit_breaker_history(requester_agent_id="echo-1")` returns `[]`; audit-ring entry has `granted=True, result_count=0`.
17. `test_query_circuit_breaker_history_logs_warning_and_returns_empty_on_store_failure` — store mock's `recent` raises `RuntimeError("disk")`; clinical role; query returns `[]`; WARNING captured; audit-ring entry `granted=True, result_count=0`.

**Optional (boundary-discovery, +0 to +1 tests, ceiling 18):**

18. `test_finalize_late_bind_attaches_store_to_breaker_when_both_present` — drive `_wire_clinical_telemetry` with both flags True + a SimpleNamespace runtime that has a `proactive_loop.circuit_breaker = CognitiveCircuitBreaker()`; manually invoke the late-bind block (or import the helper if extracted); assert `runtime.proactive_loop.circuit_breaker._history_store is runtime.clinical_telemetry._pending_breaker_store`.

The Builder MAY include test #18 within the ceiling.

### Test fixture pattern

Reuse the AD-635 fixture pattern from `tests/test_ad635_clinical_telemetry.py:25-78` (`_make_runtime` helper). For breaker hooks, mirror the AD-488 fixture pattern from existing `tests/test_ad488_*.py` (`CognitiveCircuitBreaker()` direct construction + `time.monotonic` patching where relevant).

For real-SQLite tests (#4 / #5 / #6), use `tmp_path` + a `db_path = str(tmp_path / "cbh.db")` and `asyncio.run(coro)` to drive the async append. **DO NOT use a global `data/` path** — that would pollute the dev workstation.

For clinical-query tests (#14-#17), use `AsyncMock` for the store; `_authorize_clinical_query` is exercised by the existing AD-635 helper, so re-using the fixture's `agents` dict is sufficient.

### What NOT to test (out of scope)

- Restore-on-boot of the in-memory `zone_history` (deferred to AD-635c-1).
- Retention / rotation of SQLite rows (deferred to AD-635c-2).
- Composite-index optimizer hints (deferred to AD-635c-3).
- Structured payload column (deferred to AD-635c-4).
- REST endpoint surface for `/api/clinical/circuit-breakers` (AD-635d).
- Captain Fleet-Admiral bypass of the clearance gate (AD-635e).
- Existing AD-488 / AD-506a / AD-506b / AD-635 / AD-635b tests (covered already in their own files — leave untouched).

---

## What This Does NOT Change

- `src/probos/cognitive/circuit_breaker.py` public surface: `record_event`, `should_allow_think`, `check_and_trip`, `get_status`, `get_zone`, `get_all_statuses`, `get_last_zone_transition`, `get_attention_redirect`, `reset_agent`, `reset_all`, `set_agent_traits`, `has_agent_traits` — all unchanged in signature and behavior when no history store is attached. `__init__` accepts a NEW keyword-only `history_store` parameter with default None.
- `src/probos/proactive.py` — the breaker is still constructed with the same shape (`CognitiveCircuitBreaker()` and `CognitiveCircuitBreaker(config=cb_config)`); the new `set_history_store` setter is called externally from `startup/finalize.py`, never from `proactive.py`.
- `src/probos/cognitive/clinical_telemetry.py` public surface: `query_dream_history`, `query_agent_chain_traces`, `audit_log` property, `_record_audit` signature — all unchanged.
- `src/probos/cognitive/clinical_audit_store.py` — untouched.
- `src/probos/cognitive/emergent_detector.py` — untouched.
- `src/probos/cognitive/journal.py` — untouched.
- `src/probos/events.py` — `EventType.CIRCUIT_BREAKER_TRIP` and `CircuitBreakerTripEvent` untouched.
- No new EventTypes.
- No modification of `runtime.py`.
- No modification of `src/probos/security/`, `src/probos/audit/`, or `src/probos/infrastructure/storage_backend.py` (AD-456d / AD-466 territory).
- No modification of `tests/test_ad635_clinical_telemetry.py`, `tests/test_ad635b_anomaly_audit_persistence.py`, `tests/test_ad488_*.py`, `tests/test_ad506a_*.py`, `tests/test_ad506b_*.py` (the existing tests stay green).

## Tracking Updates

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635c v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635b). |
| `docs/development/roadmap.md:5960` | Flip `*(Scoped, OSS, Issue #392)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook ConnectionFactory + late-bind sibling pattern application). |
| `prompts/wave-plan.yaml` (id: 63) | Set `status: done` post-archive. |
| GH issue #392 | Closed by Captain post-merge with commit hash. |

## Acceptance Criteria

1. Test count delta lands in [+14, +18] inclusive.
2. All existing AD-635 v1 tests in `tests/test_ad635_clinical_telemetry.py` pass unchanged.
3. All existing AD-635b tests in `tests/test_ad635b_anomaly_audit_persistence.py` pass unchanged.
4. All existing AD-488 / AD-506a / AD-506b breaker tests pass unchanged.
5. All 14+ new AD-635c tests pass.
6. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) passes with new total in [11348, 11352].
7. `CircuitBreakerHistoryStore` importable from `probos.cognitive.circuit_breaker_history_store`; constructor does not touch disk; `append` and `recent` are `async` methods; `connection_factory` parameter present; `recent(limit, *, agent_id=None)` keyword-only filter present.
8. `ClinicalTelemetryConfig.circuit_breaker_history_persistence_enabled is False` by default; `circuit_breaker_history_db_path == "data/circuit_breaker_history.db"` by default.
9. `CognitiveCircuitBreaker.__init__` accepts no new POSITIONAL parameters; instance attrs `_history_store` (init None) and `_write_tasks` (init empty set) added; new public `set_history_store(store)` setter present.
10. `ClinicalTelemetryService.__init__` accepts `circuit_breaker_history_store: CircuitBreakerHistoryStore | None = None`; default None preserves AD-635 v1 / AD-635b behavior bit-for-bit.
11. `query_circuit_breaker_history` is `async`, clearance-gated via `_authorize_clinical_query`, audit-rings every call with `query_type="circuit_breaker_history"`, returns `[]` (never raises) on denial / store-None / underlying-failure.
12. Breaker hooks: ordering preserves state mutation FIRST, transition record SECOND. A history-write failure is tier-2 log-and-degrade — does NOT propagate up through `_trip` / `should_allow_think` / `check_and_trip` / `_update_zone`.
13. `_record_transition` short-circuits when `_history_store is None` (no overhead beyond a single attribute load + None check on the no-persistence path).
14. `_wire_clinical_telemetry` is double-gated for breaker history — both `cfg.enabled` AND `cfg.circuit_breaker_history_persistence_enabled` must be True for the store to be constructed and stashed.
15. Late-bind block in `finalize_startup` (inserted inside the `if config.proactive_cognitive.enabled and runtime.ward_room:` block, immediately after `proactive_loop.set_config(...)`) attaches the pending store to the LOCAL `proactive_loop.circuit_breaker` when the clinical service has stashed one; tier-2 log-and-degrade on attach failure; silent no-op when proactive cognitive is disabled (the block doesn't run). MUST use the local `proactive_loop` variable, NOT `runtime.proactive_loop` (the latter is only assigned after `finalize_startup` returns — verified at `runtime.py:1704`).
16. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-05, HEAD `9158635`)

```
grep -n "class ClinicalTelemetryConfig" src/probos/config.py
  2027: class ClinicalTelemetryConfig(BaseModel):

grep -n "audit_max_entries\|audit_persistence_enabled\|audit_db_path" src/probos/config.py
  2035:     audit_max_entries: int = 1000
  2036:     audit_persistence_enabled: bool = False
  2037:     audit_db_path: str = "data/clinical_audit.db"

grep -n "class CognitiveCircuitBreaker" src/probos/cognitive/circuit_breaker.py
  123: class CognitiveCircuitBreaker:

grep -n "def __init__\|def _get_state\|def should_allow_think\|def check_and_trip\|def _trip\|def _update_zone\|def reset_all" src/probos/cognitive/circuit_breaker.py
   140: def __init__(
   196: def _get_state(self, agent_id: str) -> AgentBreakerState:
   280: def should_allow_think(self, agent_id: str) -> bool:
   380: def _update_zone(self, agent_id, signals, tripped) -> tuple[CognitiveZone, CognitiveZone]:
   439: def check_and_trip(self, agent_id: str) -> bool:
   479: def _trip(self, agent_id: str, reason: str) -> None:
   558: def reset_all(self) -> None:

grep -n "state.state = BreakerState\." src/probos/cognitive/circuit_breaker.py
  286:                 state.state = BreakerState.HALF_OPEN
  471:             state.state = BreakerState.CLOSED
  484:         state.state = BreakerState.OPEN

grep -n "if new_zone != old_zone:" src/probos/cognitive/circuit_breaker.py
  421:         if new_zone != old_zone:

grep -n "logger.info(\"AD-506a: Zone transition" src/probos/cognitive/circuit_breaker.py
  431:             logger.info(

grep -n "self._circuit_breaker = CognitiveCircuitBreaker" src/probos/proactive.py
  182:         self._circuit_breaker = CognitiveCircuitBreaker()
  312:             self._circuit_breaker = CognitiveCircuitBreaker(config=cb_config)

grep -n "def circuit_breaker" src/probos/proactive.py
  318:     def circuit_breaker(self) -> CognitiveCircuitBreaker:

grep -n "class ClinicalTelemetryService\|def __init__\|def query_dream_history\|def query_agent_chain_traces\|def audit_log\|def _record_audit\|def _authorize_clinical_query" src/probos/cognitive/clinical_telemetry.py
   58: class ClinicalTelemetryService:
   60:     def __init__(
   80:     async def query_dream_history(
  127:     async def query_agent_chain_traces(
  198:     @property def audit_log(self) -> list[dict[str, Any]]:
  207:     def _authorize_clinical_query(self, agent_id: str) -> bool:
  235:     def _record_audit(

grep -n "_wire_clinical_telemetry" src/probos/startup/finalize.py
  550: def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
  935:     if _wire_clinical_telemetry(runtime=runtime, config=config):

grep -n "proactive-cognitive-loop started\|proactive_loop\.set_config" src/probos/startup/finalize.py
  1006:        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)
  1027:        logger.info("proactive-cognitive-loop started (interval=%ss)", config.proactive_cognitive.interval_seconds)
  1267:        if runtime.proactive_loop is not None:

grep -n "self\.proactive_loop = fin\.proactive_loop\|self\.proactive_loop:" src/probos/runtime.py
   549:        self.proactive_loop: ProactiveCognitiveLoop | None = None
  1704:        self.proactive_loop = fin.proactive_loop
   # → confirms runtime.proactive_loop is None during finalize_startup;
   #   late-bind MUST use the local `proactive_loop` variable.

grep -n "class ConnectionFactory" src/probos/protocols.py
  223: class ConnectionFactory(Protocol):

grep -n "class ClinicalAuditStore" src/probos/cognitive/clinical_audit_store.py
   31: class ClinicalAuditStore:

grep -n "AD-635c" docs/development/roadmap.md
  5960: **AD-635c: Clinical Telemetry — Circuit Breaker State History** *(Scoped, OSS, Issue #392)*

# Highest AD across all decisions files
Get-ChildItem decisions-era-*.md, DECISIONS.md | Select-String "^### AD-([0-9]+)" -AllMatches |
  ForEach-Object { $_.Matches.Groups[1].Value -as [int] } | Sort -Descending | Select -First 1
  695   (AD-635c is unique)

pytest tests/ --co -q | tail -1
  11334 tests collected
```

All concrete claims in this prompt grep-confirmed against HEAD `9158635`. Net-new symbols introduced by Sections 0+1+2+3+4 of THIS prompt (intra-prompt-introduction — MUST NOT be flagged as missing during pre-flight phantom-API checks):

- `CircuitBreakerHistoryStore` class (Section 1)
- `CircuitBreakerHistoryStore.append`, `.recent`, `._ensure_open`, `.db_path`, `.is_open` (Section 1)
- `CognitiveCircuitBreaker` instance attrs `_history_store`, `_write_tasks` (Section 2b — initialized in the `__init__` append; **NOT** a new ctor kwarg per DLog #3 — the seam is the public setter)
- `CognitiveCircuitBreaker.set_history_store` public setter (Section 2c)
- `CognitiveCircuitBreaker._record_transition`, `._schedule_history_write`, `._write_history` (Section 2h)
- `ClinicalTelemetryService.__init__` ctor kwarg `circuit_breaker_history_store` + instance attr `_circuit_breaker_history_store` (Section 3b)
- `ClinicalTelemetryService.query_circuit_breaker_history` public method (Section 3c)
- `ClinicalTelemetryService._pending_breaker_store` instance attr set by `_wire_clinical_telemetry` (Section 4a)
- `ClinicalTelemetryConfig.circuit_breaker_history_persistence_enabled`, `.circuit_breaker_history_db_path` (Section 0)
