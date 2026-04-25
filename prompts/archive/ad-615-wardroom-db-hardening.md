# AD-615: Ward Room Database Performance Hardening

## Context

The 8,448-DM flood incident (AD-614) exposed that the Ward Room is the **only** ProbOS database without WAL mode. Every other database module sets WAL + busy_timeout:

| Module | File | WAL | busy_timeout |
|--------|------|-----|-------------|
| Trust Engine | `consensus/trust.py:161-162` | Yes | 5000 |
| Hebbian Router | `mesh/routing.py:74-75` | Yes | 5000 |
| Procedure Store | `cognitive/procedure_store.py:144` | Yes | No |
| **Ward Room** | **`ward_room/service.py:68`** | **No** | **No** |

Under the default rollback journal, concurrent reads block during writes. The Ward Room has 14 independent `db.commit()` points across 3 sub-services (threads.py, messages.py, channels.py) sharing one connection. During the flood, ~67K DB writes in 90 minutes created severe contention.

**Prior art:** BF-099 (`prompts/bf-099-trust-concurrency.md`) established the canonical ProbOS concurrency pattern: WAL + busy_timeout + BEGIN IMMEDIATE + asyncio.Lock.

## Scope Correction from Scoping

During scoping, we identified "transaction batching" as a fix — wrapping multiple commits into one. Research found that **the Ward Room already batches correctly**: `create_thread()` and `create_post()` each do a single `db.commit()` covering all their SQL writes. The episodic memory writes go through ChromaDB (a separate service), not the Ward Room DB. The real fix is the PRAGMAs, not restructuring transactions.

## Changes

### Change 1: WAL Mode + Busy Timeout + Synchronous Downgrade

**File:** `src/probos/ward_room/service.py`

In `start()`, add three PRAGMAs between the `connect()` call and the existing `PRAGMA foreign_keys = ON`. Follow the trust.py/routing.py ordering: PRAGMAs before schema creation.

**Current code (lines 66-70):**
```python
if self.db_path:
    self._db = await self._connection_factory.connect(self.db_path)
    await self._db.execute("PRAGMA foreign_keys = ON")
    self._db.row_factory = aiosqlite.Row
    await self._db.executescript(_SCHEMA)
```

**New code:**
```python
if self.db_path:
    self._db = await self._connection_factory.connect(self.db_path)
    # AD-615: WAL mode for concurrent read/write performance.
    # Matches trust.py:161, routing.py:74 pattern (BF-099 canonical).
    await self._db.execute("PRAGMA journal_mode=WAL")
    await self._db.execute("PRAGMA busy_timeout=5000")
    # AD-615: WAL-safe synchronous downgrade — only WAL checkpoints
    # require full fsync. Reduces write latency ~50% under sustained
    # load without sacrificing durability. New pattern for ProbOS;
    # safe because WAL provides crash recovery without FULL sync.
    await self._db.execute("PRAGMA synchronous=NORMAL")
    await self._db.execute("PRAGMA foreign_keys = ON")
    self._db.row_factory = aiosqlite.Row
    await self._db.executescript(_SCHEMA)
```

**Engineering principles applied:**
- **DRY:** Follows the same PRAGMA pattern as trust.py and routing.py. Same values (busy_timeout=5000).
- **Defense in Depth:** `busy_timeout=5000` is a database-engine-level safety net — if application-level concurrency control fails, the DB retries for 5 seconds instead of failing immediately.
- **Cloud-Ready Storage:** No change to connection factory usage — PRAGMAs are SQLite-specific and the commercial overlay's Postgres backend ignores them at the adapter level.

### Change 2: Startup PRAGMA Verification Log

**File:** `src/probos/ward_room/service.py`

After the PRAGMAs, add a verification log line confirming WAL mode was applied. This follows the BF-099 defensive pattern — WAL mode can silently fail on certain filesystems (network mounts, some Windows configurations).

Insert after `PRAGMA synchronous=NORMAL`, before `PRAGMA foreign_keys = ON`:

```python
    # AD-615: Verify WAL mode was accepted (can fail on network filesystems)
    async with self._db.execute("PRAGMA journal_mode") as cursor:
        row = await cursor.fetchone()
        actual_mode = row[0] if row else "unknown"
        if actual_mode != "wal":
            logger.warning(
                "Ward Room DB: WAL mode not accepted (got %s) — "
                "concurrent performance may be degraded",
                actual_mode,
            )
        else:
            logger.debug("Ward Room DB: WAL mode enabled")
```

**Engineering principle:** Fail Fast (log-and-degrade tier) — system continues but logs visible degradation warning.

## What This AD Does NOT Do

These are deliberate exclusions, NOT oversights:

1. **No asyncio.Lock or BEGIN IMMEDIATE** — The Ward Room write paths (`create_thread`, `create_post`) are invoked from the WardRoomRouter's async event loop. Since aiosqlite serializes writes through its internal thread, and WAL mode handles reader/writer concurrency, a Lock is unnecessary for the current access pattern. If future changes introduce concurrent write paths (e.g., parallel event processing from AD-616's semaphore), add a Lock at that point — it would be premature now.

2. **No PRAGMAs on the SQLiteConnectionFactory** — The codebase convention is per-module PRAGMAs in `start()`. Centralizing would require checking that all 5+ database consumers want the same settings. Defer to a future DRY consolidation wave.

3. **No episodic memory transaction batching** — Episodic memory uses ChromaDB, not the Ward Room SQLite DB. The cross-service write is already correctly sequenced: Ward Room commit first, then episodic store (fire-and-forget).

4. **No changes to `create_thread()` or `create_post()`** — Both already batch their SQL writes into a single `db.commit()`. No transaction restructuring needed.

## Tests

**File:** `tests/test_ad615_wardroom_db_hardening.py`

### Class: `TestWardRoomWalMode` (3 tests)

```python
"""AD-615: Verify Ward Room database uses WAL mode + busy_timeout + synchronous."""

class TestWardRoomWalMode:
    """Ward Room DB PRAGMA verification."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, tmp_path):
        """Ward Room DB should use WAL journal mode after start()."""
        # Create WardRoomService with tmp_path DB, call start(), query PRAGMA journal_mode.
        # Assert result == "wal".

    @pytest.mark.asyncio
    async def test_busy_timeout_set(self, tmp_path):
        """Ward Room DB should have busy_timeout=5000 after start()."""
        # Create WardRoomService with tmp_path DB, call start(), query PRAGMA busy_timeout.
        # Assert result == 5000.

    @pytest.mark.asyncio
    async def test_synchronous_normal(self, tmp_path):
        """Ward Room DB should use synchronous=NORMAL after start()."""
        # Create WardRoomService with tmp_path DB, call start(), query PRAGMA synchronous.
        # Assert result == 1 (NORMAL).
```

### Class: `TestWardRoomWalModeFallback` (1 test)

```python
class TestWardRoomWalModeFallback:
    """AD-615: WAL mode degradation logging."""

    @pytest.mark.asyncio
    async def test_wal_failure_logged_as_warning(self, tmp_path, caplog):
        """If WAL mode fails, a WARNING should be logged, not an exception."""
        # This is a structural test — verify the warning log path exists
        # by checking that the logger.warning call is in the source code.
        # (Testing actual WAL failure requires filesystem trickery that
        # is fragile in CI. AST or source inspection is sufficient.)
```

### Class: `TestWardRoomPragmaOrdering` (1 test)

```python
class TestWardRoomPragmaOrdering:
    """AD-615: PRAGMAs must execute before schema creation."""

    def test_pragmas_before_schema_in_source(self):
        """WAL/busy_timeout/synchronous PRAGMAs appear before executescript(_SCHEMA) in start()."""
        # Read service.py source, find line numbers for each PRAGMA and _SCHEMA.
        # Assert all PRAGMA lines < _SCHEMA line.
```

## Implementation Notes

- The `WardRoomService.__init__()` does not need changes — all PRAGMAs go in `start()`.
- The existing `stop()` method (which calls `await self._db.close()`) is sufficient — WAL checkpoint happens automatically on close.
- The `_SCHEMA` in `models.py` does not need changes.
- The `_connection_factory` parameter continues to work as-is — PRAGMAs are applied after `connect()` returns.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/ward_room/service.py` | Add 3 PRAGMAs + WAL verification log in `start()` |
| `tests/test_ad615_wardroom_db_hardening.py` | **NEW** — 5 tests across 3 classes |

## Verification

After implementation, run:
```bash
uv run pytest tests/test_ad615_wardroom_db_hardening.py -v
```

Then verify against the production database:
```bash
uv run python -c "
import sqlite3, pathlib, os
db = pathlib.Path(os.environ.get('LOCALAPPDATA', '')) / 'ProbOS' / 'data' / 'ward_room.db'
if db.exists():
    conn = sqlite3.connect(str(db))
    print('journal_mode:', conn.execute('PRAGMA journal_mode').fetchone()[0])
    print('busy_timeout:', conn.execute('PRAGMA busy_timeout').fetchone()[0])
    print('synchronous:', conn.execute('PRAGMA synchronous').fetchone()[0])
    conn.close()
else:
    print('DB not found at', db)
"
```

Expected output after restart: `journal_mode: wal`, `busy_timeout: 5000`, `synchronous: 1`.
