# AD-542: Abstract Database Connection Interface

## Context

The codebase has 12 production modules that all hardcode `aiosqlite.connect()` directly. Zero abstract connection interface exists. This is the single largest SOLID debt (Dependency Inversion) in the project. The commercial overlay requires swapping SQLite → Postgres without changing business logic ("Cloud-Ready Storage" principle). All 12 modules follow the identical pattern:

```python
self._db: aiosqlite.Connection | None = None

async def start(self) -> None:
    self._db = await aiosqlite.connect(self.db_path)
    await self._db.execute("PRAGMA foreign_keys = ON")
    await self._db.executescript(_SCHEMA)
    await self._db.commit()

async def stop(self) -> None:
    if self._db:
        await self._db.close()
        self._db = None
```

The seven Protocols in `protocols.py` (EpisodicMemoryProtocol, TrustNetworkProtocol, etc.) are well-designed but zero consumers import or type-annotate against them.

## Affected Files

All 12 production modules with direct `aiosqlite.connect()`:

1. `src/probos/acm.py` — `AgentCapitalManager.start()` (line ~107)
2. `src/probos/assignment.py` — `AssignmentService.start()` (line ~94)
3. `src/probos/consensus/trust.py` — `TrustNetwork.start()` (line ~106)
4. `src/probos/identity.py` — `IdentityLedger.start()` (line ~396)
5. `src/probos/persistent_tasks.py` — `PersistentTaskStore.start()` (line ~126)
6. `src/probos/mesh/routing.py` — `RoutingMesh.start()` (line ~69)
7. `src/probos/cognitive/journal.py` — `CognitiveJournal.start()` (line ~63)
8. `src/probos/skill_framework.py` — `SkillStore.start()` (line ~325)
9. `src/probos/skill_framework.py` — `QualificationStore.start()` (line ~427)
10. `src/probos/substrate/event_log.py` — `EventLog.start()` (line ~43)
11. `src/probos/ward_room.py` — `WardRoomService.start()` (line ~226)
12. `src/probos/workforce.py` — `WorkforceScheduler.start()` (line ~951)

## Requirements

### 1. Define `DatabaseConnection` Protocol

Create in `src/probos/protocols.py` (add to existing file, after the current Protocol definitions):

```python
@runtime_checkable
class DatabaseConnection(Protocol):
    """Abstract async database connection.

    Mirrors the aiosqlite.Connection API surface used throughout ProbOS.
    Commercial overlays implement this protocol for Postgres/cloud backends.
    """

    async def execute(self, sql: str, parameters: Sequence[Any] = ...) -> Any:
        """Execute a single SQL statement."""
        ...

    async def executemany(self, sql: str, parameters: Iterable[Sequence[Any]]) -> Any:
        """Execute a SQL statement for each set of parameters."""
        ...

    async def executescript(self, sql_script: str) -> None:
        """Execute a multi-statement SQL script."""
        ...

    async def fetchone(self) -> Any:
        """Fetch the next row from the last executed query."""
        ...

    async def fetchall(self) -> Any:
        """Fetch all remaining rows from the last executed query."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def close(self) -> None:
        """Close the connection."""
        ...
```

Note: The `execute()` return type is `Any` because aiosqlite returns a Cursor. The protocol doesn't constrain it — consumers use `async with self._db.execute(...) as cursor:` context manager pattern, and all backends must support this.

### 2. Define `ConnectionFactory` Protocol

Also in `src/probos/protocols.py`:

```python
@runtime_checkable
class ConnectionFactory(Protocol):
    """Factory for creating database connections.

    Default implementation wraps aiosqlite.connect().
    Commercial overlays provide Postgres/cloud implementations.
    """

    async def connect(self, db_path: str) -> DatabaseConnection:
        """Create and return a new database connection."""
        ...
```

### 3. Provide Default SQLite Implementation

Create `src/probos/storage/__init__.py` (new package) and `src/probos/storage/sqlite_factory.py`:

```python
"""Default SQLite connection factory using aiosqlite."""

from __future__ import annotations

import aiosqlite

from probos.protocols import ConnectionFactory, DatabaseConnection


class SQLiteConnectionFactory:
    """Default ConnectionFactory implementation wrapping aiosqlite.

    This is the out-of-the-box backend for all ProbOS DB modules.
    """

    async def connect(self, db_path: str) -> DatabaseConnection:
        """Open an aiosqlite connection.

        The returned connection satisfies DatabaseConnection protocol.
        aiosqlite.Connection already implements execute/executemany/
        executescript/commit/close — no wrapper needed.
        """
        conn = await aiosqlite.connect(db_path)
        return conn  # type: ignore[return-value]  # aiosqlite.Connection satisfies protocol


# Module-level singleton for convenience
default_factory = SQLiteConnectionFactory()
```

Note: `aiosqlite.Connection` already has `execute()`, `executemany()`, `executescript()`, `commit()`, `close()` — it structurally satisfies the `DatabaseConnection` protocol. No wrapper class needed. The `# type: ignore` is because aiosqlite's type stubs don't formally implement our Protocol, but structural subtyping works at runtime.

### 4. Refactor All 12 Modules — Constructor Injection

For each of the 12 modules, make two changes:

**A. Add `connection_factory` parameter to `__init__()` with a default:**

```python
from probos.protocols import ConnectionFactory

class SomeService:
    def __init__(self, ..., connection_factory: ConnectionFactory | None = None) -> None:
        ...existing params...
        self._connection_factory = connection_factory

        # Lazy import to avoid circular dependency
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
```

**Important:** The lazy import of `default_factory` inside `__init__` (guarded by `if None`) avoids circular imports and keeps the default behavior identical for all existing callers. No existing code needs to change.

**B. Replace `aiosqlite.connect()` in `start()` with `self._connection_factory.connect()`:**

Before:
```python
self._db = await aiosqlite.connect(str(self._data_dir / "whatever.db"))
```

After:
```python
self._db = await self._connection_factory.connect(str(self._data_dir / "whatever.db"))
```

**C. Update the type annotation** from `aiosqlite.Connection | None` to `DatabaseConnection | None`:

```python
from probos.protocols import ConnectionFactory, DatabaseConnection

self._db: DatabaseConnection | None = None
```

**D. Keep PRAGMA and schema init as-is.** The PRAGMA `foreign_keys = ON` and `executescript(_SCHEMA)` calls stay — these are SQLite-specific but harmless. The commercial overlay will override `start()` or provide PRAGMAs appropriate for their backend.

**E. Remove the now-unnecessary `import aiosqlite`** from each module IF the only use was `aiosqlite.connect()`. If `aiosqlite` is still used for type annotations (e.g., `aiosqlite.Row`), keep the import.

Apply this pattern to ALL 12 modules listed above. `skill_framework.py` has two classes (SkillStore + QualificationStore) — both get the factory injected.

### 5. What NOT to Change

- Do NOT modify `tests/test_ward_room.py` line 744 — the test helper's direct `aiosqlite.connect()` is fine for test isolation.
- Do NOT change `protocols.py`'s existing 7 Protocols. This AD adds DatabaseConnection and ConnectionFactory alongside them.
- Do NOT wire protocol consumption (replacing concrete class imports with Protocol type annotations) — that's a separate scope. This AD is specifically about the database connection abstraction.
- Do NOT add asyncpg, databases, or any new pip dependencies. The only new code uses existing aiosqlite.
- Do NOT create a connection pool. Each module manages its own single connection as today.
- Do NOT modify business logic in any of the 12 modules. The ONLY changes are: (a) add factory parameter, (b) replace `aiosqlite.connect()` call, (c) update type annotation.

## Tests Required

Add `tests/test_database_abstraction.py`:

1. **`test_sqlite_factory_returns_connection`** — `SQLiteConnectionFactory.connect()` returns an object that satisfies `DatabaseConnection` protocol (use `isinstance` check with the `@runtime_checkable` protocol).
2. **`test_connection_execute_and_commit`** — Create a temp DB, execute CREATE TABLE + INSERT + SELECT, verify data roundtrips.
3. **`test_connection_executescript`** — Verify `executescript()` works with multi-statement SQL.
4. **`test_connection_close`** — Verify `close()` completes without error.
5. **`test_default_factory_singleton`** — `default_factory` is importable and is a `SQLiteConnectionFactory` instance.
6. **`test_custom_factory_injected`** — Create a mock `ConnectionFactory`, inject into one module (e.g., `EventLog`), verify `start()` uses the custom factory's `connect()` instead of aiosqlite directly.
7. **`test_none_factory_defaults_to_sqlite`** — When `connection_factory=None` (default), the module creates a `SQLiteConnectionFactory` internally and works normally.
8. **`test_acm_uses_factory`** — `AgentCapitalManager(data_dir, connection_factory=mock_factory)` calls `mock_factory.connect()` in `start()`.
9. **`test_event_log_uses_factory`** — Same pattern for `EventLog`.
10. **`test_ward_room_uses_factory`** — Same pattern for `WardRoomService`.

Tests 6-10 use `AsyncMock` for the factory with `spec=ConnectionFactory`.

## Engineering Principles Compliance

- **SOLID (D):** Direct fix — concrete dependency (aiosqlite) replaced with abstract protocol (ConnectionFactory). Grade D → B+ target.
- **SOLID (O):** New backend = new ConnectionFactory impl, no modification of existing modules.
- **Cloud-Ready Storage:** Enables the commercial overlay to inject Postgres/DynamoDB/etc. at startup.
- **Fail Fast:** No exception changes — all existing error handling preserved.
- **DRY:** Factory singleton eliminates 12 redundant `import aiosqlite` + `aiosqlite.connect()` patterns.

## Verification

After implementation:
1. Run `python -m pytest tests/test_database_abstraction.py -v` — all 10 new tests pass.
2. Run `python -m pytest tests/ -x -q --timeout=30` — full suite passes, no regressions.
3. Verify: `grep -rn "aiosqlite.connect" src/probos/` returns ZERO matches (all moved to `sqlite_factory.py`).
