# AD-635b — Clinical Telemetry v2: Anomaly Audit Trail Persistence

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-635 v1 (`ClinicalTelemetryService` + `_record_audit` + bounded in-memory ring; COMPLETE), AD-542 (`ConnectionFactory` pattern; COMPLETE).
**Estimated tests:** +12 (ceiling +15)
**Closes:** GH issue #391

## Problem

`src/probos/cognitive/clinical_telemetry.py:52` declares the audit ring as a bounded `collections.deque` (default `maxlen=1000`). Every clearance-gated query call writes one row via `_record_audit(...)` (line 234) and the ring is exposed read-only via the `audit_log` property (line 172). On runtime restart, the ring is empty — every audit entry from the prior boot is lost.

DD-6 of AD-635 v1 explicitly named this gap: *"v1 in-memory only. Persistence deferred to AD-635b."* The roadmap entry for AD-635b (`docs/development/roadmap.md:5958`) names the scope: *"Persist the in-memory audit ring (`ClinicalTelemetryService._audit` deque) to SQLite for post-incident review."*

The clinical use case is concrete: Counselor Echo (ORACLE clearance, counselor agent_type) discovers a pattern of unusual `query_agent_chain_traces` calls targeting a single subordinate before a stasis recovery. Without persistence, the audit trail evaporates and the pattern cannot be reconstructed. With persistence, the SQLite `clinical_audit` table preserves every (timestamp, requester, query_type, granted, result_count, target_agent_id) row across restarts — operators query it directly via `sqlite3` for post-incident review.

## Solution

Four additive edits + one new module:

1. **`src/probos/config.py`** — extend `ClinicalTelemetryConfig` with two fields: `audit_persistence_enabled: bool = False` and `audit_db_path: str = "data/clinical_audit.db"`. Update the docstring.
2. **`src/probos/cognitive/clinical_audit_store.py` (NEW)** — `ClinicalAuditStore` class. SQLite-backed. Lazy connection via `_ensure_open()`. Optional `ConnectionFactory` injection per AD-542. Public `async append(entry: dict) -> None` and `async recent(limit: int) -> list[dict]`.
3. **`src/probos/cognitive/clinical_telemetry.py`** — `__init__` accepts `audit_store: ClinicalAuditStore | None = None`; `_record_audit` schedules a fire-and-forget write-through task after the ring append.
4. **`src/probos/startup/finalize.py`** — extend `_wire_clinical_telemetry` to construct `ClinicalAuditStore` and inject when both `cfg.enabled` AND `cfg.audit_persistence_enabled` are True.
5. **`tests/test_ad635b_anomaly_audit_persistence.py` (NEW)** — 12 tests minimum.

No EventTypes added. No modification of `audit_log` property, `query_dream_history`, `query_agent_chain_traces`, or `EmergentDetector`.

---

## Section 0 — `src/probos/config.py` (extend `ClinicalTelemetryConfig`)

**File:** `src/probos/config.py`

**SEARCH** (locks the entire `ClinicalTelemetryConfig` body verbatim — verified at HEAD lines 2027-2035):

```python
class ClinicalTelemetryConfig(BaseModel):
    """AD-635 v1: Clearance-gated clinical query facade (Medical / Counselor).

    Disabled by default — Captain opts in via YAML. v1 is read-only, has no
    automatic invocation, and surfaces nothing at runtime until a clinical
    agent invokes a query method on `runtime.clinical_telemetry`.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
```

**REPLACE** (re-emits the class + updated docstring + 2 new fields after the existing two):

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

---

## Section 1 — `src/probos/cognitive/clinical_audit_store.py` (NEW file)

**File:** `src/probos/cognitive/clinical_audit_store.py`

Create the file with this exact content:

```python
"""AD-635b: ClinicalAuditStore — SQLite-backed durable store for clinical
audit entries.

Mirrors the AD-542 ConnectionFactory pattern (cf. activation_tracker.py):
constructor accepts an optional callable returning an aiosqlite-compatible
connection; default uses ``aiosqlite.connect(db_path)`` directly. Commercial
overlays inject a Postgres / cloud factory without changing call sites.

Lifecycle:

  * ``__init__`` is sync and does NOT touch disk. The SQLite file is
    created on first ``append(...)`` via ``_ensure_open()``.
  * No explicit ``close()`` in v1 — Python GC closes file handles on
    process exit. Explicit close is part of AD-635b-1 (restore-on-boot).

Schema (v1):

  CREATE TABLE clinical_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      requester_agent_id TEXT NOT NULL,
      query_type TEXT NOT NULL,
      granted INTEGER NOT NULL,        -- 0 / 1 (SQLite has no native bool)
      result_count INTEGER NOT NULL,
      target_agent_id TEXT
  );
  CREATE INDEX idx_clinical_audit_ts ON clinical_audit(ts DESC);
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS clinical_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    requester_agent_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    granted INTEGER NOT NULL,
    result_count INTEGER NOT NULL,
    target_agent_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_clinical_audit_ts ON clinical_audit(ts DESC);
"""


class ClinicalAuditStore:
    """AD-635b: SQLite-backed audit store for ClinicalTelemetryService."""

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
        """Persist one audit row.

        ``entry`` must contain ``ts``, ``requester_agent_id``, ``query_type``,
        ``granted``, ``result_count``. ``target_agent_id`` is optional.
        """
        await self._ensure_open()
        await self._db.execute(
            "INSERT INTO clinical_audit "
            "(ts, requester_agent_id, query_type, granted, result_count, target_agent_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                float(entry["ts"]),
                str(entry["requester_agent_id"]),
                str(entry["query_type"]),
                1 if entry["granted"] else 0,
                int(entry["result_count"]),
                entry.get("target_agent_id"),
            ),
        )
        await self._db.commit()

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` most-recent rows (highest ``ts`` first)."""
        if limit <= 0:
            return []
        await self._ensure_open()
        cursor = await self._db.execute(
            "SELECT ts, requester_agent_id, query_type, granted, result_count, "
            "target_agent_id FROM clinical_audit ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        )
        rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "ts": row[0],
                "requester_agent_id": row[1],
                "query_type": row[2],
                "granted": bool(row[3]),
                "result_count": row[4],
            }
            if row[5] is not None:
                entry["target_agent_id"] = row[5]
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

## Section 2 — `src/probos/cognitive/clinical_telemetry.py` (extend)

**File:** `src/probos/cognitive/clinical_telemetry.py`

### Section 2a — extend module docstring + imports (incl. TYPE_CHECKING)

**SEARCH** (locks docstring + std imports + earned_agency import + logger line — verified at HEAD lines 1-34):

```python
"""AD-635 v1 — Clinical Telemetry Query Facade.

Clearance-gated read-only query service enabling Medical (Chapel,
chief_medical/FULL) and Counselor (Echo, counselor/ORACLE) to perform
cross-agent clinical diagnostics over substrate telemetry.

v1 surfaces TWO data domains:
  - Dream cycle history (via EmergentDetector.recent_dreams)
  - Cross-agent cognitive journal chain traces (via CognitiveJournal.get_recent_chain_traces)

Anomaly audit trail and circuit breaker state history are deferred to AD-635b/c.
REST endpoints, shell command, and proactive injection are deferred to AD-635d/e/f.

Authorization model (AD-620/622): caller must hold a clearance tier of FULL
or ORACLE (resolved via effective_recall_tier from rank + billet + active
grants) AND have a clinical agent_type. Denied queries return [] and log
a warning — they never raise. Every query is logged to a bounded in-memory
audit ring. Persistence of the audit log is deferred to AD-635b.
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any

from probos.earned_agency import (
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
    resolve_billet_clearance,
)

logger = logging.getLogger(__name__)
```

**REPLACE** (updated docstring; adds `asyncio` import; adds `TYPE_CHECKING` block between earned_agency and logger):

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

### Section 2b — extend `__init__` (accept optional `audit_store`)

**SEARCH** (locks the current ctor verbatim — verified at HEAD lines 50-54):

```python
    def __init__(self, runtime: Any, *, audit_max_entries: int = 1000) -> None:
        self._runtime = runtime
        self._audit: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=max(1, int(audit_max_entries))
        )
```

**REPLACE** (adds `audit_store` keyword + write-task tracking set; uses the forward-reference string form for the type so no runtime import is needed):

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

### Section 2c — extend `_record_audit` (append-then-schedule)

The two new helper methods (`_schedule_write_through`, `_write_through`) are appended to the end of `ClinicalTelemetryService` — `_record_audit` is the last method in the class at HEAD (line 252 is the file's last non-blank line), so the REPLACE naturally extends the class with the two helpers as its new tail.

**SEARCH** (locks the entire `_record_audit` body verbatim — verified at HEAD lines 234-252):

```python
    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
        self._audit.append(entry)
```

**REPLACE** (re-emits the body verbatim; appends fire-and-forget write-through scheduling):

```python
    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
        # In-memory ring append happens FIRST. A write-through-side failure
        # MUST NOT prevent the in-memory record (DLog #11). Tier-2 log-and-
        # degrade applies to the persistence side, not the ring.
        self._audit.append(entry)
        if self._audit_store is not None:
            self._schedule_write_through(entry)

    def _schedule_write_through(self, entry: dict[str, Any]) -> None:
        """AD-635b: fire-and-forget SQLite persistence task."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-635b: no running event loop; audit write-through skipped",
            )
            return
        task = loop.create_task(self._write_through(entry))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    async def _write_through(self, entry: dict[str, Any]) -> None:
        """AD-635b: persist one audit entry; tier-2 log-and-degrade on failure."""
        try:
            await self._audit_store.append(entry)
        except Exception:
            logger.warning(
                "AD-635b: audit write-through failed for %s/%s",
                entry.get("requester_agent_id"),
                entry.get("query_type"),
                exc_info=True,
            )
```

---

## Section 3 — `src/probos/startup/finalize.py` (extend `_wire_clinical_telemetry`)

**File:** `src/probos/startup/finalize.py`

**SEARCH** (locks the entire current wirer body verbatim — verified at HEAD lines 550-567):

```python
def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 v1: Wire ClinicalTelemetryService clearance-gated query facade."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    runtime.clinical_telemetry = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
    )
    logger.info(
        "AD-635: ClinicalTelemetryService v1 initialized "
        "(2 domains: dream_history + chain_traces; clearance gate FULL+)"
    )
    return True
```

**REPLACE** (re-emits the wirer; extends with double-gated `ClinicalAuditStore` construction):

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

---

## Section 4 — `tests/test_ad635b_anomaly_audit_persistence.py` (NEW file)

**File:** `tests/test_ad635b_anomaly_audit_persistence.py`

Create the file. Target 12 tests minimum (ceiling 15). Required test names + behaviors:

1. `test_clinical_telemetry_config_audit_persistence_default_false` — `ClinicalTelemetryConfig().audit_persistence_enabled is False`.
2. `test_clinical_telemetry_config_audit_db_path_default` — `ClinicalTelemetryConfig().audit_db_path == "data/clinical_audit.db"`.
3. `test_clinical_audit_store_constructor_does_not_touch_disk` — construct with `db_path=str(tmp_path / "x.db")`; assert `os.path.exists(...)` is False; assert `store.is_open is False`.
4. `test_clinical_audit_store_append_creates_file_lazily` — construct + `await store.append({...})`; assert file exists; `store.is_open is True`. Use `asyncio.run(...)` in the test body.
5. `test_clinical_audit_store_append_persists_row` — `await store.append(entry)` with a full entry (including `target_agent_id`); `await store.recent(10)` returns one row matching the input dict shape.
6. `test_clinical_audit_store_recent_zero_returns_empty` — `await store.recent(0) == []` even with rows present.
7. `test_clinical_audit_store_schema_columns` — after first `append`, query `PRAGMA table_info(clinical_audit)`; assert columns `id`, `ts`, `requester_agent_id`, `query_type`, `granted`, `result_count`, `target_agent_id` present with expected types (`granted` is INTEGER).
8. `test_clinical_audit_store_index_exists` — after first `append`, query `SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='clinical_audit'`; assert `idx_clinical_audit_ts` is in the result.
9. `test_clinical_audit_store_connection_factory_injected` — pass a custom `connection_factory` returning a `MagicMock` aiosqlite-compatible connection (with async `execute` / `commit`); assert the factory was called once on first `_ensure_open`; second `append` does NOT re-call.
10. `test_service_default_no_audit_store_preserves_ring_only` — construct `ClinicalTelemetryService(runtime, audit_max_entries=5)`; assert `svc._audit_store is None`; `await svc.query_dream_history(requester_agent_id="echo-1")` (granted) leaves `len(svc._write_tasks) == 0`.
11. `test_service_with_audit_store_writes_through_on_granted_query` — construct service with an `AsyncMock`-backed audit_store; run an authorized dream query inside `asyncio.run(...)`; await all `svc._write_tasks`; assert `audit_store.append` called once with an entry dict matching the expected keys; assert the in-memory ring also contains the entry.
12. `test_service_write_through_failure_keeps_ring_intact_and_logs_warning` — audit_store is an `AsyncMock` whose `append` raises `RuntimeError("disk full")`; run an authorized query; await all write tasks (or `asyncio.gather(*svc._write_tasks, return_exceptions=True)`); assert `caplog` captured a WARNING containing `AD-635b: audit write-through failed`; assert `len(svc.audit_log) == 1` (in-memory ring unaffected); assert the calling query did NOT raise.

Optional (boundary-discovery, +1 to +3 tests, ceiling 15):

13. `test_finalize_no_store_when_persistence_disabled` — `_wire_clinical_telemetry` with `audit_persistence_enabled=False` + `enabled=True`; assert `runtime.clinical_telemetry._audit_store is None`.
14. `test_finalize_constructs_store_when_both_flags_true` — `_wire_clinical_telemetry` with both flags True + `audit_db_path=str(tmp_path / "test.db")`; assert `runtime.clinical_telemetry._audit_store is not None`; assert `runtime.clinical_telemetry._audit_store.db_path` matches.
15. `test_clinical_audit_store_append_records_granted_as_integer_zero_or_one` — `await store.append({..., "granted": False, ...})`; query raw row; assert column value is `0`. Repeat with `True` → `1`.

Builder MAY include any subset of 13-15 within the ceiling.

### Test fixture pattern

For tests #11 / #12, mirror the existing AD-635 v1 fixture pattern from `tests/test_ad635_clinical_telemetry.py:25-78`:

```python
@pytest.mark.asyncio
async def test_service_with_audit_store_writes_through_on_granted_query(tmp_path):
    audit_store = AsyncMock()
    audit_store.append = AsyncMock(return_value=None)
    rt = _make_runtime(  # reuse the AD-635 helper or inline a SimpleNamespace
        agents={"echo-1": "counselor"},
        detector_dreams=[{"id": "d1"}],
    )
    svc = ClinicalTelemetryService(rt, audit_max_entries=10, audit_store=audit_store)
    await svc.query_dream_history(requester_agent_id="echo-1")
    if svc._write_tasks:
        await asyncio.gather(*svc._write_tasks, return_exceptions=True)
    assert audit_store.append.await_count == 1
    appended = audit_store.append.await_args[0][0]
    assert appended["requester_agent_id"] == "echo-1"
    assert appended["query_type"] == "dream_history"
    assert appended["granted"] is True
    assert len(svc.audit_log) == 1
```

For test #4 (real SQLite disk write), use `tmp_path` + a `db_path = str(tmp_path / "audit.db")` and `asyncio.run(coro)` to drive the async append. DO NOT use a global `data/` path — that would pollute the dev workstation.

### What NOT to test (out of scope)

- Restore-on-boot of the in-memory ring (deferred to AD-635b-1).
- A `query_audit_history` clearance-gated reader method (deferred to AD-635b-2).
- Audit-row retention / rotation (deferred to AD-635b-3).
- REST endpoint surface for audit (AD-635d).
- Captain Fleet-Admiral bypass of clearance gate (AD-635e).
- Existing AD-635 v1 audit-ring tests (covered already in `tests/test_ad635_clinical_telemetry.py` — leave untouched).

---

## What This Does NOT Change

- `src/probos/cognitive/emergent_detector.py` — `recent_dreams` and `_all_patterns` are untouched.
- `src/probos/cognitive/journal.py` — chain trace API is untouched.
- `ClinicalTelemetryService.audit_log` property — still returns the in-memory ring snapshot.
- `ClinicalTelemetryService.query_dream_history` / `query_agent_chain_traces` — public signatures unchanged.
- `_record_audit` signature (sync) — unchanged.
- No new EventTypes.
- No modification of `runtime.py`.
- No modification of `src/probos/security/`, `src/probos/audit/`, or `src/probos/infrastructure/storage_backend.py` (AD-456d / AD-466 territory).
- No modification of `tests/test_ad635_clinical_telemetry.py` (the existing 9 tests stay green).

## Tracking Updates

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635b v1 CLOSED.` paragraph. |
| `docs/development/roadmap.md:5958` | Flip `*(Scoped, OSS, Issue #391)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook ConnectionFactory pattern application). |
| `prompts/wave-plan.yaml` (id: 62) | Set `status: done` post-archive. |
| GH issue #391 | Closed by Captain post-merge with commit hash. |

## Acceptance Criteria

1. Test count delta lands in [+12, +15] inclusive.
2. All 9 existing AD-635 v1 tests in `tests/test_ad635_clinical_telemetry.py` pass unchanged.
3. All 12+ new AD-635b tests pass.
4. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) passes with new total in [11331, 11334].
5. `ClinicalAuditStore` importable from `probos.cognitive.clinical_audit_store`; constructor does not touch disk; `append` and `recent` are `async` methods; `connection_factory` parameter present.
6. `ClinicalTelemetryConfig.audit_persistence_enabled is False` by default; `audit_db_path == "data/clinical_audit.db"` by default.
7. `ClinicalTelemetryService.__init__` accepts `audit_store: ClinicalAuditStore | None = None`; default None preserves AD-635 v1 in-memory-only behavior bit-for-bit.
8. `_record_audit` ordering: in-memory ring append happens BEFORE write-through scheduling.
9. `_record_audit` stays synchronous; write-through is fire-and-forget via `asyncio.create_task`.
10. Write-through failure is tier-2 log-and-degrade (WARNING + `exc_info=True`); does NOT propagate; in-memory ring is unaffected.
11. `_wire_clinical_telemetry` is double-gated — both `cfg.enabled` AND `cfg.audit_persistence_enabled` must be True for the store to be constructed.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-05, HEAD `b2ecf20`)

```
grep -n "class ClinicalTelemetryConfig" src/probos/config.py
  2027: class ClinicalTelemetryConfig(BaseModel):

grep -n "enabled: bool = False$" src/probos/config.py | head
  2034:     enabled: bool = False
  (…and many other unrelated configs; the line at 2034 is the AD-635 enabled flag)

grep -n "audit_max_entries" src/probos/config.py
  2035:     audit_max_entries: int = 1000

grep -n "self._audit:" src/probos/cognitive/clinical_telemetry.py
  52:         self._audit: collections.deque[dict[str, Any]] = collections.deque(

grep -n "def _record_audit" src/probos/cognitive/clinical_telemetry.py
  234:     def _record_audit(

grep -n "self\._audit\.append" src/probos/cognitive/clinical_telemetry.py
  252:         self._audit.append(entry)

grep -n "def audit_log" src/probos/cognitive/clinical_telemetry.py
  172:     def audit_log(self) -> list[dict[str, Any]]:

grep -n "def __init__" src/probos/cognitive/clinical_telemetry.py | head -1
  50:     def __init__(self, runtime: Any, *, audit_max_entries: int = 1000) -> None:

grep -n "_wire_clinical_telemetry" src/probos/startup/finalize.py
  550: def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
  930:     if _wire_clinical_telemetry(runtime=runtime, config=config):

grep -n "class ConnectionFactory" src/probos/protocols.py
  223: class ConnectionFactory(Protocol):

grep -n "class DatabaseConnection" src/probos/protocols.py
  185: class DatabaseConnection(Protocol):

grep -n "connection_factory" src/probos/cognitive/activation_tracker.py
  35:     connection_factory : callable
  60:         connection_factory: Callable[..., Any] | None = None,
  72:         if self._connection_factory:
  73:             self._db = await self._connection_factory()

grep -n "AD-635b" docs/development/roadmap.md
  4148: …Same persistence pattern as AD-635b (clinical audit ring).
  5958: **AD-635b: Clinical Telemetry — Anomaly Audit Trail Persistence** *(Scoped, OSS, Issue #391)*

grep -nE "^### AD-(68[0-9]|69[0-9])" DECISIONS.md | sort -t- -k2 -n | tail -3
  207: ### AD-689 v1: Edge Population from Existing ProbOS Data (2026-05-04)
  254: ### AD-687 v1: Knowledge Edge Store (2026-05-04)
  302: ### AD-686 v1: …
  (highest in use: AD-689; AD-635b unique)

pytest tests/ --co -q | tail -1
  11319 tests collected
```

All concrete claims in this prompt grep-confirmed against HEAD `b2ecf20`. Net-new symbols (`ClinicalAuditStore`, `ClinicalAuditStore.append`, `ClinicalAuditStore.recent`, `ClinicalAuditStore._ensure_open`, `audit_store` ctor kwarg on `ClinicalTelemetryService`, `_schedule_write_through`, `_write_through`, `audit_persistence_enabled`, `audit_db_path`) are introduced by Sections 0-2 of THIS prompt — they are intra-prompt-introduction and MUST NOT be flagged as missing during pre-flight phantom-API checks.
