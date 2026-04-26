# AD-664: EventLog Diagnostic Infrastructure (Structured Payloads + Query Authority)

**Issue:** #337
**Status:** Ready for builder
**Priority:** Medium
**Depends:** None (additive to existing EventLog)
**Files:** `src/probos/substrate/event_log.py` (EDIT), `src/probos/dream_adapter.py` (EDIT), `src/probos/cognitive/emergent_detector.py` (EDIT), `src/probos/proactive.py` (EDIT), `src/probos/agents/system_qa.py` (EDIT), `src/probos/runtime.py` (EDIT), `tests/test_ad664_eventlog_diagnostic.py` (NEW)

## Problem

Two gaps block root-cause tracing through the EventLog:

1. **No structured payloads.** `EventLog.log()` accepts only flat string fields (`category`, `event`, `agent_id`, `agent_type`, `pool`, `detail`). Events like `consolidation_anomaly`, `divergence_detected`, and `emergence_trends` carry rich structured data (dicts with metrics, ratios, trend arrays), but the only place it can go is the `detail` text field — which means the data is string-serialized and un-queryable. There is no `correlation_id` or `parent_event_id` to trace causal chains (e.g., "which dream cycle produced this anomaly, and what trust updates preceded it?").

2. **No confirmed EventLog query authority.** Three places currently call `event_log.query()`: the `/log` shell command (`experience/commands/commands_introspection.py`), proactive context gathering (`proactive.py:1216`), and episodic memory cross-checking (`cognitive_agent.py:4590`). No agent has formalized diagnostic query capability — Engineering agents (Forge/Anvil) proposed 5 diagnostic relay chains but none can terminate because no agent type declares EventLog query as an authorized capability.

**Scope:**
- Add structured payload (`data` JSON column) and tracing fields (`correlation_id`, `parent_event_id`) to EventLog schema and `log()` method
- Add `query_structured()` method for querying by correlation_id or payload fields
- Retrofit callers that emit `consolidation_anomaly`, `emergence_trends`, and `divergence_detected` events to include structured payloads and correlation IDs
- Add `eventlog_diagnostic_query` capability to EngineeringAgent, formalizing query authority
- Tests for schema migration, structured logging, query methods, and capability declaration

**What this does NOT include:**
- Migrating ALL existing `event_log.log()` callers to structured payloads (future — this AD targets the three emergent-detection event types plus system events)
- A dedicated EventLog API router (future — HXI diagnostic panel)
- EventLog federation or cross-instance query (future)

---

## Section 1: EventLog Schema Migration — Structured Payload + Tracing Columns

**File:** `src/probos/substrate/event_log.py` (EDIT)

### Step 1a: Update the schema DDL

The current `_SCHEMA` creates a table with columns: `id`, `timestamp`, `category`, `event`, `agent_id`, `agent_type`, `pool`, `detail`.

Add three new columns. Replace the existing `_SCHEMA` string with:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    event           TEXT    NOT NULL,
    agent_id        TEXT,
    agent_type      TEXT,
    pool            TEXT,
    detail          TEXT,
    correlation_id  TEXT,
    parent_event_id INTEGER,
    data            TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_category ON events (category);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id);
"""
```

**Column semantics:**
- `correlation_id` (TEXT, nullable) — groups causally related events. For dream cycles, use the dream report's timestamp or a UUID. For intent broadcasts, use `msg.id`. Allows `SELECT * WHERE correlation_id = ?` to get the full causal chain.
- `parent_event_id` (INTEGER, nullable) — references `events.id` of the directly preceding event in a chain. Not a foreign key constraint (events may be pruned). Enables tree-structured event tracing.
- `data` (TEXT, nullable) — JSON-serialized structured payload. Stores the evidence dicts, metrics, trend arrays that currently get string-dumped into `detail`.

### Step 1b: Add schema migration for existing databases

In `start()`, after the `executescript(_SCHEMA)` call, add migration logic. This must be idempotent — if columns already exist, do nothing.

```python
    async def start(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # AD-664: Migrate existing databases — add new columns if missing
        await self._migrate_ad664()
        logger.info("EventLog opened: %s", self.db_path)

    async def _migrate_ad664(self) -> None:
        """Add correlation_id, parent_event_id, data columns if missing (AD-664)."""
        if not self._db:
            return
        try:
            async with self._db.execute("PRAGMA table_info(events)") as cursor:
                columns = {row[1] async for row in cursor}
            migrations = []
            if "correlation_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN correlation_id TEXT")
            if "parent_event_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN parent_event_id INTEGER")
            if "data" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN data TEXT")
            for sql in migrations:
                await self._db.execute(sql)
            # Always ensure indexes exist — IF NOT EXISTS makes this idempotent
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id)"
            )
            if migrations:
                await self._db.commit()
                logger.info("AD-664: Migrated EventLog schema (%d columns added)", len(migrations))
        except Exception:
            logger.debug("AD-664: EventLog migration check failed", exc_info=True)
```

**Why idempotent migration:** Existing installs have the old schema. New installs get the full schema from `_SCHEMA`. The migration handles the gap. `PRAGMA table_info` returns column metadata — checking column names is safe and fast.

---

## Section 2: Update `log()` Method + Add `query_structured()`

**File:** `src/probos/substrate/event_log.py` (EDIT)

### Step 2a: Extend `log()` signature

Add three new keyword-only parameters to `log()`. All existing callers pass the existing params positionally or by keyword — the new params are keyword-only with `None` defaults, so **zero existing callers break**.

Replace the current `log()` method:

```python
    async def log(
        self,
        category: str,
        event: str,
        agent_id: str | None = None,
        agent_type: str | None = None,
        pool: str | None = None,
        detail: str | None = None,
        *,
        correlation_id: str | None = None,
        parent_event_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """Append an event to the log.

        Returns the inserted row ID (for parent_event_id chaining),
        or None if the database is not available.

        AD-664: New keyword-only params:
        - correlation_id: groups causally related events
        - parent_event_id: references the preceding event's row ID
        - data: structured payload (dict, JSON-serialized on write)
        """
        if not self._db:
            return None
        now = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(data, default=str) if data is not None else None
        cursor = await self._db.execute(
            "INSERT INTO events "
            "(timestamp, category, event, agent_id, agent_type, pool, detail, "
            " correlation_id, parent_event_id, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, category, event, agent_id, agent_type, pool, detail,
             correlation_id, parent_event_id, data_json),
        )
        await self._db.commit()
        return cursor.lastrowid
```

**Key change:** `log()` now returns `int | None` (the inserted row ID) instead of `None`. This enables callers to chain `parent_event_id`:
```python
row_id = await event_log.log("emergent", "consolidation_anomaly", ...)
await event_log.log("emergent", "consolidation_detail", ..., parent_event_id=row_id)
```

The module-level `import json` (added in Step 2e) handles serialization. No inline import needed.

### Step 2b: Update `query()` to return new columns

The existing `query()` method returns dicts with keys `id`, `timestamp`, `category`, `event`, `agent_id`, `agent_type`, `pool`, `detail`. Extend it to include the new columns:

Replace the `query()` method:

```python
    async def query(
        self,
        category: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query recent events, optionally filtered.

        AD-664: Results now include correlation_id, parent_event_id, and
        data (deserialized from JSON).
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
        conditions = []
        params: list[str] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(str(limit))

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                data_raw = row[10]
                try:
                    data_parsed = json.loads(data_raw) if data_raw else None
                except (ValueError, TypeError):
                    data_parsed = None
                rows.append({
                    "id": row[0],
                    "timestamp": row[1],
                    "category": row[2],
                    "event": row[3],
                    "agent_id": row[4],
                    "agent_type": row[5],
                    "pool": row[6],
                    "detail": row[7],
                    "correlation_id": row[8],
                    "parent_event_id": row[9],
                    "data": data_parsed,
                })
        return rows
```

### Step 2c: Add `query_structured()` for correlation and payload queries

Add a new method after `query()`:

```python
    async def query_structured(
        self,
        *,
        correlation_id: str | None = None,
        category: str | None = None,
        event: str | None = None,
        parent_event_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with structured filtering (AD-664).

        Supports querying by correlation_id (causal chain), event name,
        and parent_event_id (direct predecessor).

        Returns same dict shape as query(), with deserialized data field.
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
        conditions = []
        params: list = []

        if correlation_id is not None:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if event is not None:
            conditions.append("event = ?")
            params.append(event)
        if parent_event_id is not None:
            conditions.append("parent_event_id = ?")
            params.append(parent_event_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                data_raw = row[10]
                try:
                    data_parsed = json.loads(data_raw) if data_raw else None
                except (ValueError, TypeError):
                    data_parsed = None
                rows.append({
                    "id": row[0],
                    "timestamp": row[1],
                    "category": row[2],
                    "event": row[3],
                    "agent_id": row[4],
                    "agent_type": row[5],
                    "pool": row[6],
                    "detail": row[7],
                    "correlation_id": row[8],
                    "parent_event_id": row[9],
                    "data": data_parsed,
                })
        return rows
```

### Step 2d: Add `get_event_chain()` for tree traversal

Add a convenience method for walking a parent chain:

```python
    async def get_event_chain(self, event_id: int, max_depth: int = 20) -> list[dict]:
        """Walk the parent_event_id chain from a given event upward (AD-664).

        Returns events from the given event up to the root (parent_event_id is NULL),
        ordered from root to leaf. Stops at max_depth to prevent infinite loops
        from data corruption.
        """
        if not self._db:
            return []

        chain: list[dict] = []
        current_id: int | None = event_id

        for _ in range(max_depth):
            if current_id is None:
                break
            sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
                   "pool, detail, correlation_id, parent_event_id, data "
                   "FROM events WHERE id = ?")
            async with self._db.execute(sql, (current_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                break
            data_raw = row[10]
            try:
                data_parsed = json.loads(data_raw) if data_raw else None
            except (ValueError, TypeError):
                data_parsed = None
            chain.append({
                "id": row[0],
                "timestamp": row[1],
                "category": row[2],
                "event": row[3],
                "agent_id": row[4],
                "agent_type": row[5],
                "pool": row[6],
                "detail": row[7],
                "correlation_id": row[8],
                "parent_event_id": row[9],
                "data": data_parsed,
            })
            current_id = row[9]  # parent_event_id

        chain.reverse()  # root-to-leaf order
        return chain
```

### Step 2e: Add `Any` and `json` imports

Add to the imports at the top of `event_log.py`:

```python
import json
from typing import Any
```

The existing imports are `logging`, `datetime`, `timezone`, `Path`, and `ConnectionFactory`/`DatabaseConnection` from `probos.protocols`. The `Any` import is needed for the `data: dict[str, Any]` parameter type. The module-level `import json` is used by the `log()`, `query()`, `query_structured()`, and `get_event_chain()` methods for JSON serialization/deserialization.

---

## Section 3: Retrofit Emergent Pattern Event Logging

Three event types currently emit bare string `detail` with no structured `data`. This section adds structured payloads and correlation IDs.

### Step 3a: DreamAdapter — emergent patterns get structured payloads

**File:** `src/probos/dream_adapter.py` (EDIT)

The `_event_log_emergent` method (line 218) currently logs:
```python
await self._event_log.log(
    category="emergent",
    event=pattern.pattern_type,
    detail=pattern.description,
)
```

Replace with:

```python
    async def _event_log_emergent(self, pattern: Any, correlation_id: str | None = None) -> None:
        """Log emergent pattern to event log with structured payload (AD-664)."""
        if self._event_log:
            await self._event_log.log(
                category="emergent",
                event=pattern.pattern_type,
                detail=pattern.description,
                correlation_id=correlation_id,
                data={
                    "confidence": pattern.confidence,
                    "severity": pattern.severity,
                    "evidence": pattern.evidence,
                    "pattern_type": pattern.pattern_type,
                },
            )
```

Then update the caller. In `on_emergent_patterns` (around line 138), where patterns are iterated:

**Builder verification step:** Search for `self._event_log_emergent(pattern)` in `dream_adapter.py`. The call is inside a loop like:

```python
loop.create_task(self._event_log_emergent(pattern))
```

Replace with:

```python
loop.create_task(self._event_log_emergent(pattern, correlation_id=correlation_id))
```

The `correlation_id` needs to be derived from the dream cycle. All patterns from one `on_emergent_patterns` invocation share a single correlation_id (one per dream cycle). Add at the top of `on_emergent_patterns` (before the pattern loop):

```python
import uuid
correlation_id = f"dream-{uuid.uuid4().hex[:12]}"
```

Then pass it to each `_event_log_emergent` call.

### Step 3b: Runtime — mesh events get correlation IDs

**File:** `src/probos/runtime.py` (EDIT)

The runtime's `broadcast_intent` and `broadcast_intent_consensus` methods log mesh events. These already have a natural correlation ID: `msg.id` (the intent message ID).

**Target 1:** `broadcast_intent` method — find the `event_log.log` call (around line 1722):

```python
await self.event_log.log(
    category="mesh",
    event="intent_broadcast",
    detail=f"intent={intent} id={msg.id[:8]}",
)
```

Replace with:

```python
broadcast_row_id = await self.event_log.log(
    category="mesh",
    event="intent_broadcast",
    detail=f"intent={intent} id={msg.id[:8]}",
    correlation_id=msg.id,
    data={"intent": intent, "msg_id": msg.id, "ttl_seconds": msg.ttl_seconds},
)
```

**Target 2:** The `intent_resolved` log call nearby (around line 1750). Chain it to the broadcast event via `parent_event_id`:

```python
await self.event_log.log(
    category="mesh",
    event="intent_resolved",
    detail=f"intent={intent} id={msg.id[:8]} results={len(results)}",
)
```

Replace with:

```python
await self.event_log.log(
    category="mesh",
    event="intent_resolved",
    detail=f"intent={intent} id={msg.id[:8]} results={len(results)}",
    correlation_id=msg.id,
    data={
        "intent": intent,
        "msg_id": msg.id,
        "result_count": len(results),
        "agent_ids": [r.agent_id for r in results] if results else [],
    },
    parent_event_id=broadcast_row_id,
)
```

**Note:** If the broadcast `log()` call returned `None` (DB unavailable), `parent_event_id` will also be `None` — the chain breaks gracefully since the column accepts null values.
```

**Target 3:** `broadcast_intent_consensus` — find its `intent_broadcast` log call (around line 1785) and its `intent_resolved` log call (around line 1919). Apply the same pattern: add `correlation_id=msg.id` and a `data=` dict with the intent, msg_id, and result count. Both calls are confirmed to exist at these approximate line numbers.

**Builder verification step:** `grep -n "event_log.log" src/probos/runtime.py` to find ALL event_log.log calls. There are 17 calls. Only the mesh and consensus calls (4 total: lines ~1722, ~1750, ~1785, ~1919) need correlation_id updates in this AD. The others (lifecycle, qa, cognitive) are future work.

### Step 3c: SystemQA — smoke test events get correlation IDs

**File:** `src/probos/agents/system_qa.py` (EDIT)

The smoke test lifecycle emits `smoke_test_started` and `smoke_test_complete` events (lines 295, 356). These should share a correlation ID.

Find the `smoke_test_started` call (line 295):
```python
await self._runtime.event_log.log(
    category="qa",
    event="smoke_test_started",
    detail=f"{record.agent_type}: {len(cases)} tests",
)
```

Above this block, generate a correlation ID:
```python
import uuid
qa_correlation_id = f"qa-{uuid.uuid4().hex[:12]}"
```

Then add `correlation_id=qa_correlation_id` to both the `smoke_test_started` call (line 295) and the `smoke_test_complete` call (line 356) that follows in the same method.

**Builder note:** Search for all `event_log.log` calls in `system_qa.py` — there are 2 (lines 295 and 356). Add `correlation_id=qa_correlation_id` to each. Do NOT pass `data=` payloads here — the existing `detail` strings are sufficient for QA events. This is about correlation only.

---

## Section 4: Diagnostic Query Authority for Engineering Agents

**File:** `src/probos/cognitive/engineering_officer.py` (EDIT)

EngineeringAgent (callsign LaForge) currently has two capabilities:
- `engineering_analyze` — system and architecture analysis
- `engineering_optimize` — performance and architecture optimization

Add a third capability for EventLog diagnostic queries.

### Step 4a: Add capability descriptor and update `_handled_intents`

In the `default_capabilities` list (line 36), add:

```python
CapabilityDescriptor(can="eventlog_diagnostic_query", detail="AD-664: Query EventLog for structured diagnostic data and causal chains"),
```

In the `_handled_intents` set (line 52), add the new intent so the cognitive chain dispatches it to this agent:

```python
_handled_intents = {"engineering_analyze", "engineering_optimize", "eventlog_diagnostic_query"}
```

### Step 4b: Add intent descriptor

In the `intent_descriptors` list (line 40), add:

```python
IntentDescriptor(
    name="eventlog_diagnostic_query",
    params={
        "correlation_id": "optional correlation ID to trace a causal chain",
        "category": "optional event category filter (e.g., emergent, mesh, qa)",
        "event": "optional event name filter (e.g., consolidation_anomaly)",
        "limit": "max results (default 50)",
    },
    description="Query the EventLog for structured diagnostic events, causal chains, and system health data",
),
```

### Step 4c: Update instructions

In the `_INSTRUCTIONS` string (line 10), add a new paragraph before the closing sentence:

Find the line:
```python
"Respond with thorough, well-reasoned engineering analysis."
```

Insert before it:

```python
"When you receive an eventlog_diagnostic_query intent:\n"
"1. Query the EventLog for events matching the specified filters.\n"
"2. If a correlation_id is provided, trace the full causal chain.\n"
"3. Analyze the structured payload data for anomalies and root causes.\n"
"4. Present findings with evidence from the event data.\n\n"
```

### Step 4d: Scope note — no programmatic handler in this AD

CognitiveAgent dispatches intents via the LLM-driven cognitive lifecycle (`_run_cognitive_lifecycle`, line 2696) or registered skill handlers (`self._skills`, line 2671). It does **not** use `getattr(self, f"handle_{intent.name}")` dispatch. A method named `handle_eventlog_diagnostic_query` would never be called.

This AD delivers **capability declaration only**: the `_handled_intents` gate (Step 4a) ensures the intent reaches EngineeringAgent instead of being self-deselected, and the instructions (Step 4c) tell the LLM how to reason about diagnostic queries. The LLM can analyze any structured data provided in its perception context but cannot programmatically call `query_structured()` on its own.

**Follow-up:** A future AD should implement a proper diagnostic query handler — either as a registered skill handler (via `self._skills[intent_name]`) or via a tool-feeding pattern (override `perceive()` to pre-fetch EventLog data into the LLM context). This requires design analysis of how the LLM should consume structured EventLog rows and is out of scope for AD-664.

---

## Section 5: Tests

**File:** `tests/test_ad664_eventlog_diagnostic.py` (NEW)

### Test categories (17 tests):

**Schema migration (3 tests):**

1. `test_eventlog_new_schema_has_columns` — Create EventLog with a fresh DB, verify `correlation_id`, `parent_event_id`, `data` columns exist in `PRAGMA table_info`.

2. `test_eventlog_migration_idempotent` — Create EventLog, call `start()` twice. Second call must not error. Verify columns still exist.

3. `test_eventlog_migration_adds_missing_columns` — Create EventLog with old schema (no new columns), then call `_migrate_ad664()`. Verify columns were added.

**Structured logging (4 tests):**

4. `test_log_with_structured_data` — Call `log(category="emergent", event="consolidation_anomaly", data={"weights_strengthened": 42, "ratio": 2.1})`. Query back. Verify `data` is a dict (deserialized), not a string.

5. `test_log_with_correlation_id` — Call `log()` with `correlation_id="dream-abc123"`. Query back. Verify `correlation_id` field.

6. `test_log_returns_row_id` — Call `log()`, verify return value is an integer > 0.

7. `test_log_parent_event_id_chain` — Log event A (no parent). Log event B with `parent_event_id=A's row ID`. Query back. Verify B's `parent_event_id` equals A's `id`.

**Query methods (5 tests):**

8. `test_query_returns_new_columns` — Log an event with all new fields. Call `query()`. Verify result dict has `correlation_id`, `parent_event_id`, `data` keys.

9. `test_query_structured_by_correlation` — Log 3 events: 2 with correlation_id "chain-1", 1 with "chain-2". Call `query_structured(correlation_id="chain-1")`. Verify 2 results.

10. `test_query_structured_by_event_name` — Log events with different `event` names. Call `query_structured(event="consolidation_anomaly")`. Verify only matching events returned.

11. `test_query_structured_combined_filters` — Log events with varying category + event. Call `query_structured(category="emergent", event="consolidation_anomaly")`. Verify AND filtering.

12. `test_get_event_chain` — Log a chain: A (root) -> B (parent=A) -> C (parent=B). Call `get_event_chain(C.id)`. Verify returns [A, B, C] in root-to-leaf order.

**Backward compatibility (2 tests):**

13. `test_log_without_new_params_still_works` — Call `log(category="system", event="pool_created", pool="test")` with NO new params. Verify it succeeds and returns an int. Verify `correlation_id` is None, `parent_event_id` is None, `data` is None in the result.

14. `test_query_old_shape_preserved` — Log old-style event. Call `query()`. Verify existing keys (`id`, `timestamp`, `category`, `event`, `agent_id`, `agent_type`, `pool`, `detail`) are all present alongside new keys.

**Engineering capability (2 tests):**

15. `test_engineering_agent_has_diagnostic_capability` — Import `EngineeringAgent`. Verify `"eventlog_diagnostic_query"` is in `[c.can for c in EngineeringAgent.default_capabilities]`.

16. `test_engineering_agent_has_diagnostic_intent` — Verify `"eventlog_diagnostic_query"` is in `[i.name for i in EngineeringAgent.intent_descriptors]`.

17. `test_engineering_agent_handled_intents` — Verify `"eventlog_diagnostic_query"` is in `EngineeringAgent._handled_intents` (line 52) so the cognitive chain dispatches it.

### Test implementation notes:

- Use `tmp_path` fixture for SQLite DB paths (standard pattern in ProbOS tests)
- EventLog constructor: `EventLog(db_path=tmp_path / "test_events.db")`
- Call `await event_log.start()` in each test (or use a fixture)
- Call `await event_log.stop()` in teardown
- For migration test 3, manually create the old schema first, then construct EventLog and call start
- For capability tests, no runtime or async needed — just import and check class attributes

### Test skeleton:

```python
"""Tests for AD-664: EventLog Diagnostic Infrastructure."""

from __future__ import annotations

import pytest

from probos.substrate.event_log import EventLog


@pytest.fixture
async def event_log(tmp_path):
    el = EventLog(db_path=tmp_path / "test_events.db")
    await el.start()
    yield el
    await el.stop()


# --- Schema migration ---

@pytest.mark.asyncio
async def test_eventlog_new_schema_has_columns(event_log):
    async with event_log._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    assert "parent_event_id" in columns
    assert "data" in columns


@pytest.mark.asyncio
async def test_eventlog_migration_idempotent(tmp_path):
    el = EventLog(db_path=tmp_path / "test.db")
    await el.start()
    await el.start()  # second call must not error
    async with el._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    await el.stop()


@pytest.mark.asyncio
async def test_eventlog_migration_adds_missing_columns(tmp_path):
    """Simulate old schema, then migrate."""
    import aiosqlite
    db = await aiosqlite.connect(str(tmp_path / "old.db"))
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            category  TEXT    NOT NULL,
            event     TEXT    NOT NULL,
            agent_id  TEXT,
            agent_type TEXT,
            pool      TEXT,
            detail    TEXT
        );
    """)
    await db.commit()
    await db.close()

    el = EventLog(db_path=tmp_path / "old.db")
    await el.start()
    async with el._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    assert "parent_event_id" in columns
    assert "data" in columns
    await el.stop()


# --- Structured logging ---

@pytest.mark.asyncio
async def test_log_with_structured_data(event_log):
    await event_log.log(
        category="emergent",
        event="consolidation_anomaly",
        data={"weights_strengthened": 42, "ratio": 2.1},
    )
    rows = await event_log.query(category="emergent")
    assert len(rows) == 1
    assert rows[0]["data"] == {"weights_strengthened": 42, "ratio": 2.1}
    assert isinstance(rows[0]["data"], dict)


@pytest.mark.asyncio
async def test_log_with_correlation_id(event_log):
    await event_log.log(
        category="emergent",
        event="test",
        correlation_id="dream-abc123",
    )
    rows = await event_log.query(category="emergent")
    assert rows[0]["correlation_id"] == "dream-abc123"


@pytest.mark.asyncio
async def test_log_returns_row_id(event_log):
    row_id = await event_log.log(category="test", event="ping")
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.asyncio
async def test_log_parent_event_id_chain(event_log):
    id_a = await event_log.log(category="test", event="root")
    id_b = await event_log.log(category="test", event="child", parent_event_id=id_a)
    rows = await event_log.query(category="test", limit=10)
    child = [r for r in rows if r["event"] == "child"][0]
    assert child["parent_event_id"] == id_a


# --- Query methods ---

@pytest.mark.asyncio
async def test_query_returns_new_columns(event_log):
    await event_log.log(
        category="test", event="x",
        correlation_id="c1", parent_event_id=None,
        data={"key": "val"},
    )
    rows = await event_log.query(category="test")
    assert "correlation_id" in rows[0]
    assert "parent_event_id" in rows[0]
    assert "data" in rows[0]


@pytest.mark.asyncio
async def test_query_structured_by_correlation(event_log):
    await event_log.log(category="e", event="a", correlation_id="chain-1")
    await event_log.log(category="e", event="b", correlation_id="chain-1")
    await event_log.log(category="e", event="c", correlation_id="chain-2")
    rows = await event_log.query_structured(correlation_id="chain-1")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_query_structured_by_event_name(event_log):
    await event_log.log(category="emergent", event="consolidation_anomaly")
    await event_log.log(category="emergent", event="emergence_trends")
    rows = await event_log.query_structured(event="consolidation_anomaly")
    assert len(rows) == 1
    assert rows[0]["event"] == "consolidation_anomaly"


@pytest.mark.asyncio
async def test_query_structured_combined_filters(event_log):
    await event_log.log(category="emergent", event="consolidation_anomaly")
    await event_log.log(category="mesh", event="consolidation_anomaly")
    await event_log.log(category="emergent", event="other")
    rows = await event_log.query_structured(
        category="emergent", event="consolidation_anomaly",
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_event_chain(event_log):
    id_a = await event_log.log(category="test", event="root")
    id_b = await event_log.log(category="test", event="mid", parent_event_id=id_a)
    id_c = await event_log.log(category="test", event="leaf", parent_event_id=id_b)
    chain = await event_log.get_event_chain(id_c)
    assert len(chain) == 3
    assert chain[0]["event"] == "root"   # root first
    assert chain[2]["event"] == "leaf"   # leaf last


# --- Backward compatibility ---

@pytest.mark.asyncio
async def test_log_without_new_params_still_works(event_log):
    row_id = await event_log.log(
        category="system", event="pool_created", pool="test",
    )
    assert isinstance(row_id, int)
    rows = await event_log.query(category="system")
    assert rows[0]["correlation_id"] is None
    assert rows[0]["parent_event_id"] is None
    assert rows[0]["data"] is None


@pytest.mark.asyncio
async def test_query_old_shape_preserved(event_log):
    await event_log.log(
        category="lifecycle", event="agent_wired",
        agent_id="a1", agent_type="test", pool="p1", detail="test detail",
    )
    rows = await event_log.query(category="lifecycle")
    r = rows[0]
    for key in ("id", "timestamp", "category", "event", "agent_id",
                "agent_type", "pool", "detail",
                "correlation_id", "parent_event_id", "data"):
        assert key in r, f"Missing key: {key}"


# --- Engineering capability ---

def test_engineering_agent_has_diagnostic_capability():
    from probos.cognitive.engineering_officer import EngineeringAgent
    caps = [c.can for c in EngineeringAgent.default_capabilities]
    assert "eventlog_diagnostic_query" in caps


def test_engineering_agent_has_diagnostic_intent():
    from probos.cognitive.engineering_officer import EngineeringAgent
    intents = [i.name for i in EngineeringAgent.intent_descriptors]
    assert "eventlog_diagnostic_query" in intents


def test_engineering_agent_handled_intents():
    from probos.cognitive.engineering_officer import EngineeringAgent
    assert "eventlog_diagnostic_query" in EngineeringAgent._handled_intents
```

---

## Engineering Principles Compliance

- **SOLID/S** — EventLog remains a single-purpose append-only log store. New columns and methods extend its responsibility without splitting it — structured data is still "event logging." Query authority lives on the agent (EngineeringAgent), not the store.
- **SOLID/O** — `log()` extended via new keyword-only params with None defaults. Zero existing callers change. `query()` extended with additional result keys — callers that destructure only old keys are unaffected.
- **SOLID/L** — EventLog's public `log()` / `query()` shape is preserved (existing callers use kwargs/positionals that still match). New keyword-only params with `None` defaults maintain backward compatibility.
- **Law of Demeter** — Callers use `event_log.log()` and `event_log.query_structured()`. No reaching through internals. `runtime.event_log` is a public attribute (line 184 of runtime.py).
- **Fail Fast** — `_migrate_ad664` catches exceptions and logs debug (non-critical — existing schema still works). `query_structured()` returns empty list if DB unavailable. JSON parse failures degrade to `None`.
- **DRY** — Row-to-dict conversion appears in `query()`, `query_structured()`, and `get_event_chain()`. Builder SHOULD extract a `_row_to_dict(row)` helper method on EventLog to avoid the triple copy. This is a simple extraction — take the `row[0]` through `row[10]` dict construction + JSON parse into a private method.
- **Defense in Depth** — `data` is JSON-serialized on write and deserialized on read with try/except. `parent_event_id` is not a foreign key (events may be pruned). `max_depth` on `get_event_chain` prevents infinite loops.
- **Cloud-Ready Storage** — EventLog already uses `ConnectionFactory` / `DatabaseConnection` protocols (line 9-10 of event_log.py). New columns are standard SQL. No SQLite-specific features used.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   AD-664 COMPLETE. EventLog Diagnostic Infrastructure — structured payload (data JSON column), correlation_id, parent_event_id tracing columns. Schema migration for existing DBs. query_structured() and get_event_chain() methods. Retrofitted dream/emergent, mesh, and QA events with structured payloads + correlation IDs. Engineering diagnostic query capability declared (capability + _handled_intents + LLM instructions); programmatic handler deferred to follow-up AD. 17 tests. Issue #337.
   ```

2. **docs/development/roadmap.md** — Update the AD-664 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ### AD-664 — EventLog Diagnostic Infrastructure (2026-04-26)
   **Context:** EventLog events carried only flat string fields with no structured payload, correlation ID, or parent chain. Root-cause tracing impossible. No agent held formalized EventLog query authority — Engineering diagnostic relay chains dead-ended. Crew-originated (Forge + Anvil, 5 proposals). Issue #337.
   **Decision:** Added three columns to EventLog schema: correlation_id (TEXT), parent_event_id (INTEGER), data (TEXT/JSON). Extended log() with keyword-only params (zero existing callers break). log() now returns row ID for parent chaining. Added query_structured() for correlation/event filtering and get_event_chain() for parent-chain traversal. Retrofitted emergent pattern events (consolidation_anomaly, emergence_trends via DreamAdapter), mesh events (intent_broadcast, intent_resolved), and QA events with structured payloads and correlation IDs. Declared eventlog_diagnostic_query capability on EngineeringAgent with _handled_intents gate and LLM instructions; programmatic query handler deferred to follow-up AD (requires skill registration or tool-feeding pattern design). Idempotent schema migration handles existing databases.
   **Consequences:** Engineering agents can now terminate diagnostic relay chains by querying structured EventLog data. Causal chains are traceable via correlation_id (e.g., all events from one dream cycle) and parent_event_id (direct predecessor links). Future: migrate remaining callers to structured payloads, add EventLog API router for HXI diagnostic panel, federation-level event correlation.
   ```
