# AD-490 v1 — EventLog hash chain (substrate-tier tamper detection)

**Issue:** [#506](https://github.com/seangalliher/ProbOS/issues/506)
**Type:** Architecture Decision (substrate hardening)
**Depends on:** AD-456 (`security/audit.py` AuditLog) — pattern to mirror; AD-664 (`event_log.py` migration scaffolding).
**Wave:** 129

## Goal

The substrate `EventLog` (SQLite `events` table) records every lifecycle, mesh, and system event but stores them as plain rows — any external write to the database tampers silently. AD-456 already shipped a hash-chained `AuditLog` for security records (in-memory + AD-456d SQLite persistence) using a SHA-256 prior-hash chain. This AD lifts the same pattern into `EventLog`: every appended row carries `prev_hash` and `row_hash` columns; `verify_chain()` walks the table and reports the first break (or returns `(True, None)` if intact).

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/substrate/event_log.py:14–32` defines `_SCHEMA` with the `events` table; current columns: `id, timestamp, category, event, agent_id, agent_type, pool, detail, correlation_id, parent_event_id, data` (last three added by AD-664 migration at `:62–87`).
- ✅ `src/probos/substrate/event_log.py:99–131` `async def log(...)` is the single insert site; returns `cursor.lastrowid` or None.
- ✅ `src/probos/substrate/event_log.py:62–87` `_migrate_ad664()` is the canonical `ALTER TABLE ADD COLUMN` migration pattern — read it before drafting D2.
- ✅ `src/probos/security/audit.py:1–7` declares the AD-456 hash-chain pattern: `entry_hash = sha256(payload)` where payload includes `prior_hash`. Genesis = `"0" * 64`.
- ✅ `src/probos/security/audit.py:69–75` shows the canonical hash-input shape: `{sequence, timestamp, category, detail, prior_hash}`.
- ✅ `src/probos/security/audit.py:121` defines `verify_chain() -> bool` walking the in-memory list. AD-490 needs a richer return type (per dispatch: `(ok: bool, broken_at: int | None)`) since it walks a SQL table by `id`.
- ✅ `events` table primary key is `id INTEGER PRIMARY KEY AUTOINCREMENT` — chain order = ascending `id`.
- ✅ `EventLog._connection_factory` is a `ConnectionFactory` Protocol (`probos.protocols`) — tests can inject in-memory factories per the cloud-ready storage rule.
- ⚠️ `src/probos/substrate/event_log.py:120` currently produces `data_json` via `json.dumps(data, default=str)` — **without `sort_keys=True`**. The hash chain's determinism contract requires `sort_keys=True` so the same payload rehashes identically during `verify_chain()`. D4 below pins this.

## Scope

Add a SHA-256 prior-hash chain to the `events` table with a single migration, a single `log()` write-path change, and a single new `verify_chain()` walker. Do NOT introduce a separate hash table, do NOT change the `log()` public signature, do NOT remove the AD-664 migration.

## Deliverables

### D1. Schema additions in `src/probos/substrate/event_log.py`

Extend `_SCHEMA` (the new-database CREATE path) to include the two new columns and the genesis sentinel index:

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
    data            TEXT,
    prev_hash       TEXT NOT NULL DEFAULT '',
    row_hash        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_category ON events (category);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
"""
```

Add a class constant `GENESIS_HASH: str = "0" * 64` mirroring `AuditLog.GENESIS_HASH`.

### D2. Add `_migrate_ad490()` migration in `event_log.py`

Mirror the existing `_migrate_ad664()` shape. After AD-664 migration runs, also:

```python
async def _migrate_ad490(self) -> None:
    """Add prev_hash, row_hash columns if missing (AD-490)."""
    if not self._db:
        return
    try:
        async with self._db.execute("PRAGMA table_info(events)") as cursor:
            columns = {row[1] async for row in cursor}
        migrations = []
        if "prev_hash" not in columns:
            migrations.append(
                "ALTER TABLE events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''"
            )
        if "row_hash" not in columns:
            migrations.append(
                "ALTER TABLE events ADD COLUMN row_hash TEXT NOT NULL DEFAULT ''"
            )
        for sql in migrations:
            await self._db.execute(sql)
        if migrations:
            await self._db.commit()
            logger.info(
                "AD-490: Migrated EventLog hash chain (%d columns added)",
                len(migrations),
            )
    except Exception:
        logger.debug("AD-490: EventLog migration check failed", exc_info=True)
```

Call from `start()` immediately after `await self._migrate_ad664()`.

### D3. Hash computation helper

Module-level (top of `event_log.py`):

```python
import hashlib

def _compute_row_hash(*, prev_hash: str, payload: dict[str, Any]) -> str:
    """SHA-256 over (prev_hash || canonical_json(payload)).

    Mirrors AD-456 AuditLog._hash() but operates on a serialized row dict.
    Canonical form = ``json.dumps(payload, sort_keys=True, default=str)``
    so the same row produces the same hash on rehash during verification.
    """
    serialized = json.dumps(payload, sort_keys=True, default=str)
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(serialized.encode("utf-8"))
    return h.hexdigest()
```

Payload shape (must be deterministic — verification recomputes it identically):

```python
payload = {
    "timestamp": now,
    "category": category,
    "event": event,
    "agent_id": agent_id,
    "agent_type": agent_type,
    "pool": pool,
    "detail": detail,
    "correlation_id": correlation_id,
    "parent_event_id": parent_event_id,
    "data": data_json,
}
```

### D4. Update `log()` write path

Inside `log()` after `data_json` is computed and before the INSERT:

0. **Determinism contract (in-scope fix)**: change the existing `data_json = json.dumps(data, default=str) if data is not None else None` at `event_log.py:120` to `data_json = json.dumps(data, sort_keys=True, default=str) if data is not None else None`. Without `sort_keys=True`, two semantically identical payloads with different dict insertion order would produce different `data_json` strings, breaking `verify_chain()` rehash equality. This is the only existing-code change AD-490 makes outside of additive surfaces.
1. Read the previous row's `row_hash` via a single `SELECT row_hash FROM events ORDER BY id DESC LIMIT 1`. If empty (first ever row), `prev_hash = self.GENESIS_HASH`.
2. Compute `row_hash = _compute_row_hash(prev_hash=prev_hash, payload=payload)`.
3. INSERT both columns alongside the existing fields.

Keep `log()`'s public signature unchanged. Caller behavior is identical — chain integrity is internal.

### D5. New `verify_chain()` method on `EventLog`

```python
async def verify_chain(self) -> tuple[bool, int | None]:
    """AD-490: Walk the events table by id; return (ok, broken_at).

    Returns (True, None) if every row's row_hash equals the recomputed
    hash of (prev row's row_hash || canonical_json(payload)). Returns
    (False, broken_id) on the first mismatch, where broken_id is the
    ``id`` of the offending row. Empty table -> (True, None).

    Walks in ascending id order. Reads all columns the hash payload
    depends on. Does not modify the database.
    """
```

Implementation: open one cursor `SELECT id, timestamp, category, event, agent_id, agent_type, pool, detail, correlation_id, parent_event_id, data, prev_hash, row_hash FROM events ORDER BY id ASC`. Maintain a running `expected_prev = self.GENESIS_HASH`. For each row: rebuild the payload dict (same keys as D3), recompute `_compute_row_hash(prev_hash=expected_prev, payload=payload)`. If recomputed hash != stored `row_hash`, return `(False, row.id)`. If `prev_hash` column != `expected_prev`, also return `(False, row.id)`. Set `expected_prev = row.row_hash` and continue.

If the table is empty (no rows fetched), return `(True, None)`.

### D6. Tests in new file `tests/test_ad490_eventlog_hash_chain.py`

Minimum 8 tests, using a tmp_path SQLite file or an in-memory connection factory:

1. `test_log_first_event_uses_genesis_hash` — prev_hash on row 1 is `"0" * 64`.
2. `test_log_second_event_chains_to_first` — row 2's `prev_hash` equals row 1's `row_hash`.
3. `test_compute_row_hash_is_pure` — direct purity assertion on the helper: call `_compute_row_hash(prev_hash="X", payload={"k": "v"})` twice with identical args, assert the two return values are equal. The helper is a pure function of (prev_hash, payload).
4. `test_verify_chain_empty_returns_ok_none` — fresh log, no rows.
5. `test_verify_chain_intact_after_three_logs` — `(True, None)` after three writes.
6. `test_verify_chain_detects_tampered_row` — UPDATE one row's `detail` directly via SQL, expect `(False, that_row_id)`.
7. `test_verify_chain_detects_tampered_prev_hash` — UPDATE `prev_hash` on a middle row, expect `(False, that_row_id)`.
8. `test_migration_adds_columns_to_legacy_db` — pre-create a DB with only the AD-664 columns (no prev_hash/row_hash), then `start()` and confirm `PRAGMA table_info` includes both new columns.

All tests `@pytest.mark.asyncio`. Use `aiosqlite`-compatible tmp DB; reuse `default_factory` from `probos.storage.sqlite_factory`.

## Non-Goals

- Do NOT add an in-memory hash chain (the SQLite chain is the source of truth — there is no AuditLog-style entries list here).
- Do NOT add a federation export of the chain (separate AD).
- Do NOT modify `AuditLog`, `security/audit.py`, or AD-456 behavior.
- Do NOT change any existing callers of `log()` — chain integrity is transparent.
- Do NOT add a new EventType for chain breaks (verification is on-demand; alerting is a separate AD).
- Do NOT introduce a new config field — chain enforcement is unconditional in v1.

## Acceptance

- Focused: `pytest tests/test_ad490_eventlog_hash_chain.py -v -n 0` — 8/8 pass.
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes. Existing `EventLog` consumers must continue to pass unchanged (the chain columns are additive).
- `git diff` shows changes only in: `src/probos/substrate/event_log.py` and the new test file. No callers of `log()` need to change.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#506](https://github.com/seangalliher/ProbOS/issues/506).
- DECISIONS.md entry stub: AD-490 — extends AD-456 hash-chain pattern from AuditLog to substrate EventLog; on-disk SHA-256 prior-hash chain with `verify_chain()` walker.

## Revision (2026-05-08)

- **Recommended #1 applied**: Pinned the `data_json` determinism contract. Verified-Against-Codebase now flags that `event_log.py:120` currently uses `json.dumps(data, default=str)` without `sort_keys=True`. D4 step 0 makes the in-scope fix — add `sort_keys=True` to that single existing call — so identical payloads with different dict insertion order rehash identically during `verify_chain()`.
- **Recommended #2 applied**: Renamed and rephrased test #3 from "deterministic_for_same_input" (with the hard-to-parse "modulo prev_hash linkage" qualifier) to `test_compute_row_hash_is_pure` — a direct purity assertion calling `_compute_row_hash(prev_hash="X", payload={...})` twice with identical args and asserting equality. The intent ("the helper is a pure function") is now stated, not implied.
