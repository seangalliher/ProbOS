# AD-466: Engineering Infrastructure -- Backup & StorageBackend ABC

**Status:** Ready for builder
**Dependencies:** Builds on existing `ConnectionFactory` Protocol (`protocols.py:223`) and `SQLiteConnectionFactory` (`storage/sqlite_factory.py:10`). Reads `runtime.data_dir` public property (verified at `runtime.py:934`, post-AD-468). **AD-466 OWNS `src/probos/infrastructure/__init__.py` directory creation** if package is created (mirrors AD-455's `security/`, AD-457's `agents/engineering/`, AD-459's `degradation/` precedents).
**Estimated tests:** ~12
**Risk:** Medium -- new top-level package; touches `runtime.py` for backup-service wiring; no consensus paths affected.

---

## Problem

ProbOS has SQLite databases under `runtime.data_dir`: `events.db`, `hebbian_weights.db`, `trust.db`, `episodic.db`, etc. (verified at `runtime.py:289-339`). There is no:

1. **Backup primitive.** No periodic snapshot of `data_dir` SQLite files. A reset or disk failure loses all state.
2. **StorageBackend abstraction.** The `ConnectionFactory` Protocol (`protocols.py:223`) and `SQLiteConnectionFactory` (`storage/sqlite_factory.py:10`) are SQLite-specific. A future PostgreSQL migration has no clean seam.

`grep -rn "BackupService\|StorageBackend" src/probos/` returns no matches.

The `infrastructure/` directory does not exist (`Test-Path src/probos/infrastructure` returns False). AD-466 owns creation.

The roadmap entry (line 4177) lists 5 capabilities: Backup/Restore, CI/CD pipeline, Observability, Storage abstraction, Operations runbook. Three are out of v1 scope:

- **CI/CD pipeline** -- `.github/workflows/ci.yml` and `docs.yml` already exist (verified). v1 does NOT modify CI workflows.
- **Observability** -- `substrate/telemetry.py` already provides `TelemetryService` (verified at `substrate/telemetry.py:71`). v1 does NOT add a competing observability surface.
- **Operations runbook** -- documentation deliverable, not a Python change.

## Solution Overview

Create `src/probos/infrastructure/` package with two real-work primitives:

1. **`BackupService`** -- snapshots SQLite files under `runtime.data_dir` to a configured backup directory using SQLite's online `.backup` API (no need to stop the runtime). Stateless on construction; each `snapshot()` call writes a timestamped subdirectory. Emits `BACKUP_COMPLETE` on success, `BACKUP_FAILED` on error.
2. **`StorageBackend` ABC** -- an explicit abstract base extending the existing `ConnectionFactory` Protocol. v1 ships `SQLiteStorageBackend` (delegates to `SQLiteConnectionFactory`). PostgreSQL implementation deferred to AD-466b.

This is **infrastructure-layer additive work.** AD-466 does NOT change `ConnectionFactory` Protocol, does NOT modify any existing DB module, does NOT add a CI/CD workflow file, does NOT touch `substrate/telemetry.py`. It composes the existing storage layer into a backup-friendly surface and prepares the ABC seam for future PostgreSQL.

**v1 scope (no-theater discipline per Wave 5 retrospective convention #7):**

The roadmap's 5 capabilities reduce to 2 real-work v1 deliverables:

- **`BackupService`** -- shipped, real work today.
- **`StorageBackend` ABC + SQLite default** -- shipped, real work today (replaces direct `SQLiteConnectionFactory` import sites in startup with `runtime.storage_backend` indirection -- prepares PostgreSQL seam without implementing it).

Three deferred:

- **CI/CD pipeline changes** -- not v1 scope; `.github/workflows/ci.yml` (existing) is unchanged. AD-466 does not modify any `.github/workflows/*.yml` file.
- **Observability** -- existing `TelemetryService` covers the surface. Any extension is AD-466b scope.
- **Operations runbook** -- documentation deliverable, deferred.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
BACKUP_COMPLETE = "backup_complete"  # AD-466
BACKUP_FAILED = "backup_failed"  # AD-466
```

Two new values. Verified absent via `grep -n "BACKUP_COMPLETE\|BACKUP_FAILED" src/probos/events.py` (no matches).

---

## Section 1: Create `src/probos/infrastructure/` package

**IMPORTANT:** `src/probos/infrastructure/` does NOT exist. Create `src/probos/infrastructure/__init__.py` first -- same pattern as AD-455 `security/`, AD-459 `degradation/`.

```python
"""Engineering Infrastructure -- backup, storage abstraction (AD-466)."""

from probos.infrastructure.backup import BackupResult, BackupService
from probos.infrastructure.storage_backend import (
    SQLiteStorageBackend,
    StorageBackend,
)

__all__ = [
    "BackupResult",
    "BackupService",
    "SQLiteStorageBackend",
    "StorageBackend",
]
```

---

## Section 2: `BackupService` and `BackupResult`

**File:** `src/probos/infrastructure/backup.py` (new)

Uses Python stdlib `sqlite3` online-backup API (no new pyproject deps -- per Wave 5 retrospective convention #2).

```python
"""AD-466: BackupService -- timestamped SQLite snapshots under data_dir."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupResult:
    """Result of a backup snapshot."""

    succeeded: bool
    snapshot_dir: str
    files_copied: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    duration_seconds: float = 0.0
    error: str = ""


class BackupService:
    """Periodic snapshot of SQLite databases under runtime.data_dir.

    Stateless on construction. Each `snapshot()` call writes a timestamped
    subdirectory under `backup_root` and copies every `*.db` file from
    `data_dir` using SQLite's online `.backup` API (which works while the
    source database is being read/written).

    Caller is responsible for scheduling. v1 does not run a background task.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        backup_root: Path,
        emit_event: Any | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._backup_root = backup_root
        self._emit_event = emit_event

    def snapshot(self) -> BackupResult:
        """Take one timestamped snapshot. Returns BackupResult regardless of outcome."""
        started = time.time()
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
        snapshot_dir = self._backup_root / timestamp
        try:
            snapshot_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            # Sub-second collision -- append microsecond suffix
            snapshot_dir = self._backup_root / f"{timestamp}-{int((started % 1) * 1_000_000):06d}"
            snapshot_dir.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            return self._fail(str(snapshot_dir), started, f"mkdir failed: {exc}")

        files_copied: list[str] = []
        bytes_copied = 0
        try:
            db_files = sorted(self._data_dir.glob("*.db"))
            for src in db_files:
                dest = snapshot_dir / src.name
                self._backup_one(src, dest)
                files_copied.append(src.name)
                try:
                    bytes_copied += dest.stat().st_size
                except OSError:
                    pass
            result = BackupResult(
                succeeded=True,
                snapshot_dir=str(snapshot_dir),
                files_copied=files_copied,
                bytes_copied=bytes_copied,
                duration_seconds=time.time() - started,
            )
            self._emit_complete(result)
            return result
        except Exception as exc:
            logger.error(
                "AD-466: backup snapshot failed (snapshot_dir=%s, files_copied=%d): %s",
                snapshot_dir, len(files_copied), exc,
            )
            return self._fail(str(snapshot_dir), started, str(exc))

    def _backup_one(self, src: Path, dest: Path) -> None:
        """SQLite online backup -- safe while source is being written."""
        try:
            with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dest)) as dest_conn:
                src_conn.backup(dest_conn)
        except sqlite3.Error:
            # Fall back to a file-copy. Acceptable when src isn't currently
            # being written; the SQLite WAL semantics may produce a slightly
            # inconsistent snapshot, but a fallback is preferable to skipping.
            shutil.copyfile(src, dest)

    def _fail(self, snapshot_dir: str, started: float, error: str) -> BackupResult:
        result = BackupResult(
            succeeded=False,
            snapshot_dir=snapshot_dir,
            duration_seconds=time.time() - started,
            error=error,
        )
        self._emit_failed(result)
        return result

    def _emit_complete(self, result: BackupResult) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.BACKUP_COMPLETE,
                {
                    "snapshot_dir": result.snapshot_dir,
                    "files_copied": list(result.files_copied),
                    "bytes_copied": result.bytes_copied,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception:
            logger.warning(
                "AD-466: BACKUP_COMPLETE emit failed (snapshot_dir=%s)",
                result.snapshot_dir, exc_info=True,
            )

    def _emit_failed(self, result: BackupResult) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.BACKUP_FAILED,
                {
                    "snapshot_dir": result.snapshot_dir,
                    "error": result.error,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception:
            logger.warning(
                "AD-466: BACKUP_FAILED emit failed (snapshot_dir=%s)",
                result.snapshot_dir, exc_info=True,
            )
```

---

## Section 3: `StorageBackend` ABC and `SQLiteStorageBackend`

**File:** `src/probos/infrastructure/storage_backend.py` (new)

Wraps the existing `ConnectionFactory` Protocol + `SQLiteConnectionFactory`. Provides a typed seam future PostgreSQL implementations can satisfy.

```python
"""AD-466: StorageBackend ABC -- typed seam over ConnectionFactory.

v1 ships SQLiteStorageBackend (delegates to SQLiteConnectionFactory).
PostgreSQL implementation deferred to AD-466b.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract storage backend.

    Concrete subclasses provide a `ConnectionFactory` that produces
    `DatabaseConnection` instances for ProbOS modules (event_log,
    cognitive_journal, etc.). v1 ships SQLiteStorageBackend; future
    PostgreSQL backend will subclass without changing consumers.
    """

    name: str = "abstract"

    @abstractmethod
    def connection_factory(self) -> "ConnectionFactory":
        """Return a ConnectionFactory consumers can use."""

    @abstractmethod
    async def connect(self, db_path: str) -> "DatabaseConnection":
        """Open a connection. Convenience pass-through to factory.connect()."""


class SQLiteStorageBackend(StorageBackend):
    """SQLite-backed storage. The default v1 backend."""

    name = "sqlite"

    def __init__(self) -> None:
        from probos.storage.sqlite_factory import default_factory
        self._factory = default_factory

    def connection_factory(self) -> "ConnectionFactory":
        return self._factory

    async def connect(self, db_path: str) -> "DatabaseConnection":
        return await self._factory.connect(db_path)
```

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

REPLACE:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    BACKUP_COMPLETE = "backup_complete"  # AD-466
    BACKUP_FAILED = "backup_failed"  # AD-466
```

> Builder note: anchor `INFODYNAMIC_REPORT` is verified post-AD-491 (Wave 6). Fallback chain: `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190) is the always-available terminal anchor.

---

## Section 5: Add `InfrastructureConfig`

**File:** `src/probos/config.py`

```python
class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"
```

Wire into `SystemConfig`:

SEARCH:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

REPLACE:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    infrastructure: InfrastructureConfig = InfrastructureConfig()  # AD-466
```

> Builder note: anchor-chain fallback (next-anchor if predecessor hasn't landed):
> 1. `infodynamic: InfodynamicConfig` (AD-491, post-Wave 6).
> 2. `degradation: DegradationConfig` (AD-459, post-Wave 6).
> 3. `engineering: EngineeringConfig` (AD-457, post-Wave 6).
> 4. `validation_framework: ValidationFrameworkConfig` (AD-451, post-Wave 6).
> 5. `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593) -- always-available terminal fallback.

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-491 InfodynamicProbe block:

```python
    # AD-466: Engineering Infrastructure (BackupService + StorageBackend)
    if config.infrastructure.enabled:
        from probos.infrastructure import (
            BackupService,
            SQLiteStorageBackend,
        )
        runtime.storage_backend = SQLiteStorageBackend()
        if config.infrastructure.backup_enabled:
            backup_root = runtime.data_dir / config.infrastructure.backup_subdir
            backup_root.mkdir(parents=True, exist_ok=True)
            runtime.backup_service = BackupService(
                data_dir=runtime.data_dir,
                backup_root=backup_root,
                emit_event=runtime.emit_event,
            )
            logger.info(
                "AD-466: BackupService wired (backup_root=%s)",
                backup_root,
            )
        else:
            runtime.backup_service = None
        logger.info("AD-466: StorageBackend wired (sqlite)")
```

> Verify-first: `runtime.data_dir` is a public property post-AD-468 (verified at `runtime.py:934`). `runtime.emit_event` is the post-AD-680 public method. `runtime.storage_backend` and `runtime.backup_service` are published as public attributes (no leading underscore) per Wave 5 retrospective convention #1.

---

## Tests

**File:** `tests/test_ad466_infrastructure.py`

12 tests:

1. `test_event_type_backup_complete_exists` -- `EventType.BACKUP_COMPLETE.value == "backup_complete"`.
2. `test_event_type_backup_failed_exists` -- `EventType.BACKUP_FAILED.value == "backup_failed"`.
3. `test_infrastructure_config_defaults` -- `InfrastructureConfig()` defaults: `enabled=True`, `backup_enabled=True`, `backup_subdir="backups"`.
4. `test_backup_service_snapshot_creates_timestamped_dir` -- `tmp_path` + 1 dummy `.db` file -> snapshot dir created with timestamped name; file copied. `BackupResult.succeeded=True`.
5. `test_backup_service_snapshot_handles_no_db_files` -- empty `data_dir` -> snapshot succeeds with `files_copied=[]`.
6. `test_backup_service_snapshot_emits_complete_event` -- `emit` mock fires once with `BACKUP_COMPLETE` containing `snapshot_dir`, `files_copied`, `bytes_copied`, `duration_seconds`.
7. `test_backup_service_snapshot_emits_failed_event_on_unwritable_root` -- `backup_root` cannot be created (e.g., parent is a file) -> `BACKUP_FAILED` event with `error` populated.
8. `test_backup_service_uses_online_backup_api` -- in-memory test SQLite source; backup happens via `sqlite3.Connection.backup`. Smoke test that the path executes without exception.
9. `test_backup_service_falls_back_to_file_copy_on_sqlite_error` -- corrupted source `.db` (e.g., empty file) -> falls back to `shutil.copyfile`; `BackupResult.succeeded=True`.
10. `test_storage_backend_sqlite_returns_factory` -- `SQLiteStorageBackend().connection_factory()` returns the singleton `default_factory`.
11. `test_storage_backend_sqlite_connect_passes_through` -- `await SQLiteStorageBackend().connect(":memory:")` returns a working connection. `@pytest.mark.asyncio`.
12. `test_storage_backend_abc_cannot_be_instantiated_directly` -- `StorageBackend()` raises `TypeError` (abstract methods).

Each test uses `tmp_path` for filesystem fixtures. No shared mutable state.

---

## What This Does NOT Change

- `ConnectionFactory` Protocol (`protocols.py:223`) is unchanged. `StorageBackend` ABC composes it.
- `SQLiteConnectionFactory` (`storage/sqlite_factory.py:10`) is unchanged. `SQLiteStorageBackend` delegates to it.
- Existing `event_log.py`, `cognitive_journal.py`, `trust.py`, etc. continue to use `ConnectionFactory` directly. They are NOT migrated to `runtime.storage_backend` in v1 -- the ABC is shipped as a future-friendly seam, not retrofitted now.
- `substrate/telemetry.py` (`TelemetryService`) is unchanged. Observability remains its job.
- `.github/workflows/*.yml` files are unchanged. AD-466 does NOT touch CI/CD.
- No background task. The Builder/operator schedules `BackupService.snapshot()` calls.
- Documentation runbook deferred. AD-466 produces no `docs/` changes.
- **PostgreSQL implementation deferred to AD-466b** (extends `StorageBackend` ABC).
- **Observability deliverable deferred to AD-466c** if the existing `TelemetryService` surface proves insufficient.
- **CI/CD pipeline deliverable deferred to AD-466d** if Python-side validation needs bespoke workflow changes.

---

## Tracking

- `PROGRESS.md`: add `AD-466 CLOSED. Engineering Infrastructure -- ...`
- `docs/development/roadmap.md`: flip AD-466 status from `*(planned)*` to `*(complete)*` near line 4177.
- `DECISIONS.md`: optional entry recording the v1-2-capabilities + 3-deferred-sub-AD scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/infrastructure/__init__.py`: 13 lines (new -- owns directory creation).
- `src/probos/infrastructure/backup.py`: ~145 lines (new).
- `src/probos/infrastructure/storage_backend.py`: ~50 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~7 lines added.
- `src/probos/startup/finalize.py`: ~22 lines added.
- `tests/test_ad466_infrastructure.py`: ~250 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad466_infrastructure.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `src/probos/infrastructure/__init__.py` exists (AD-466 owns creation).
- `runtime.storage_backend` and `runtime.backup_service` are public attributes (no leading underscore).
- `BackupService` uses stdlib only (`sqlite3`, `shutil`, `pathlib`); no new pyproject deps.
- `StorageBackend` is abstract -- direct instantiation raises `TypeError`.
- `.github/workflows/*.yml` files are unchanged.
- `substrate/telemetry.py` is unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/infrastructure/
  (does NOT exist -- AD-466 creates it; verified via Test-Path returning False)

grep -n "class ConnectionFactory\|class DatabaseConnection" src/probos/protocols.py
  186: class DatabaseConnection(Protocol):
  223: class ConnectionFactory(Protocol):

grep -n "class SQLiteConnectionFactory\|default_factory" src/probos/storage/sqlite_factory.py
  10: class SQLiteConnectionFactory:

grep -n "self\._data_dir\|def data_dir" src/probos/runtime.py
  289: self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
  290: self._checkpoint_dir = self._data_dir / "checkpoints"
  314: self.event_log = EventLog(db_path=self._data_dir / "events.db")
  933: @property
  934: def data_dir(self) -> Path:
  (public property post-AD-468; AD-466 reads `runtime.data_dir`)

grep -n "class TelemetryService" src/probos/substrate/telemetry.py
  71: class TelemetryService:
  (AD-466 does NOT touch -- observability stays here)

ls .github/workflows/
  ci.yml  docs.yml
  (AD-466 does NOT modify -- CI is out of v1 scope)

grep -n "BACKUP_COMPLETE\|BACKUP_FAILED\|BackupService\|StorageBackend" src/probos/
  (no matches -- AD-466 introduces these names)

grep -n "AGENT_SELF_NAMED\|INFODYNAMIC_REPORT" src/probos/events.py
  190: AGENT_SELF_NAMED = "agent_self_named"  # AD-499
  (terminal fallback)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback)

grep -n "def emit_event" src/probos/runtime.py
  775: def emit_event(self, event: BaseEvent | str | EventType, ...
```
