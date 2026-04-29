# AD-524: Ship's Archive — Generational Knowledge Persistence

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~9

---

## Problem

ProbOS resets destroy all learned state — episodic memory, trust, Hebbian
weights, dreams. There is no mechanism for knowledge to persist across resets
(generational learning). Ship's Records (AD-434) is Git-backed and instance-
scoped; it gets wiped on reset. The Oracle Service (AD-462e) queries three
tiers (episodic, records, operational) but has no cross-reset tier.

Agents have requested this capability: Chapel proposed "exit notes" before
reset, and crew cold-start gaps include missing duty reports and institutional
knowledge from prior timelines.

## Fix

### Section 1: Create `ArchiveStore` — cross-reset SQLite persistence

**File:** `src/probos/knowledge/archive_store.py` (new file)

An append-only SQLite store that lives **outside** the instance `data_dir`,
so resets don't touch it. Uses the Cloud-Ready Storage pattern (abstract
connection factory, not direct `aiosqlite.connect()`).

```python
"""Ship's Archive — cross-reset generational knowledge persistence (AD-524).

Stores curated knowledge entries that survive resets. Entries are append-only
(no updates, no deletes). Each entry records which timeline (instance) it
came from and when it was archived.

Storage location: {archive_dir}/archive.db (outside instance data_dir).
Default archive_dir: platform-specific ProbOS home / archive/
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveEntry:
    """A single archived knowledge entry."""

    id: int
    timeline_id: str  # Instance/ship DID or UUID at time of archival
    category: str  # "duty_report" | "lesson_learned" | "exit_note" | "procedure" | "observation"
    title: str
    content: str
    author_agent_type: str  # Agent type that authored/curated the entry
    author_callsign: str  # Callsign at time of archival
    archived_at: float  # Unix timestamp
    metadata: dict[str, Any]  # Arbitrary metadata (JSON)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_agent_type TEXT NOT NULL DEFAULT '',
    author_callsign TEXT NOT NULL DEFAULT '',
    archived_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);
"""


class ArchiveStore:
    """Append-only cross-reset knowledge store (AD-524).

    Uses ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

    async def initialize(self) -> None:
        """Open database and create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-524: ArchiveStore initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def append(
        self,
        *,
        timeline_id: str,
        category: str,
        title: str,
        content: str,
        author_agent_type: str = "",
        author_callsign: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Append an entry to the archive. Returns the entry ID.

        This is the ONLY write operation. No updates, no deletes.
        """
        import json

        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")

        now = time.time()
        meta_json = json.dumps(metadata or {})

        cursor = await self._db.execute(
            """INSERT INTO archive
               (timeline_id, category, title, content, author_agent_type,
                author_callsign, archived_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (timeline_id, category, title, content, author_agent_type,
             author_callsign, now, meta_json),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def search(
        self,
        query: str,
        *,
        category: str = "",
        limit: int = 10,
    ) -> list[ArchiveEntry]:
        """Search archive entries by keyword match on title and content.

        Simple LIKE-based search. Future: full-text search or vector embeddings.
        """
        import json

        if not self._db:
            return []

        # Escape LIKE wildcards in user input (defense in depth)
        _escaped = query.replace("%", "\\%").replace("_", "\\_")
        conditions = ["(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"]
        params: list[Any] = [f"%{_escaped}%", f"%{_escaped}%"]

        if category:
            conditions.append("category = ?")
            params.append(category)

        sql = f"""SELECT id, timeline_id, category, title, content,
                         author_agent_type, author_callsign, archived_at, metadata
                  FROM archive
                  WHERE {' AND '.join(conditions)}
                  ORDER BY archived_at DESC
                  LIMIT ?"""
        params.append(limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        return [
            ArchiveEntry(
                id=row[0],
                timeline_id=row[1],
                category=row[2],
                title=row[3],
                content=row[4],
                author_agent_type=row[5],
                author_callsign=row[6],
                archived_at=row[7],
                metadata=json.loads(row[8]) if row[8] else {},
            )
            for row in rows
        ]

    async def get_recent(self, limit: int = 20) -> list[ArchiveEntry]:
        """Get the most recent archive entries (no filter)."""
        import json

        if not self._db:
            return []

        cursor = await self._db.execute(
            """SELECT id, timeline_id, category, title, content,
                     author_agent_type, author_callsign, archived_at, metadata
              FROM archive ORDER BY archived_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            ArchiveEntry(
                id=row[0], timeline_id=row[1], category=row[2],
                title=row[3], content=row[4], author_agent_type=row[5],
                author_callsign=row[6], archived_at=row[7],
                metadata=json.loads(row[8]) if row[8] else {},
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total number of archive entries."""
        if not self._db:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM archive")
        row = await cursor.fetchone()
        return row[0] if row else 0
```

### Section 2: Add `ArchiveConfig` to SystemConfig

**File:** `src/probos/config.py`

Add configuration for the archive. Follow the `RecordsConfig` pattern
(config.py:683-719). Insert near the `RecordsConfig` class definition.

```python
class ArchiveConfig(BaseModel):
    """Ship's Archive configuration (AD-524)."""

    enabled: bool = True
    db_path: str = ""  # Empty = {platform_archive_dir}/archive.db
```

Add `archive: ArchiveConfig = ArchiveConfig()` to `SystemConfig`.

Find the `SystemConfig` class and its fields. Grep for:
```
grep -n "records:" src/probos/config.py
```

Then add `archive: ArchiveConfig = ArchiveConfig()` near the `records` field.

The `db_path` default is empty — resolved at runtime to a platform-specific
location outside `data_dir`. The resolution logic goes in the startup module
(Section 4).

### Section 3: Integrate Archive as Oracle Tier 4

**File:** `src/probos/cognitive/oracle_service.py`

Add the archive as a fourth tier in the Oracle Service.

**Step 1:** Add `archive_store` parameter to `__init__`:

SEARCH:
```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
```

REPLACE:
```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
```

**Step 2:** Add archive tier to `query()`. Update the default tiers list and
add a Tier 4 query block after Tier 3:

SEARCH:
```python
        active_tiers = tiers or ["episodic", "records", "operational"]
```

REPLACE:
```python
        active_tiers = tiers or ["episodic", "records", "operational", "archive"]
```

Add after the Tier 3 block (after the `except` for operational, around line 138):

```python
        # Tier 4: Ship's Archive (AD-524) — cross-reset knowledge
        if self._archive_store and "archive" in active_tiers:
            try:
                tier_results = await self._query_archive(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 4 (archive) query failed", exc_info=True)
```

**Step 3:** Add the `_query_archive` method. Follow the pattern of
`_query_records`:

```python
    async def _query_archive(
        self, query_text: str, *, k: int = 5,
    ) -> list[OracleResult]:
        """Query the Ship's Archive for cross-reset knowledge."""
        entries = await self._archive_store.search(query_text, limit=k)
        results = []
        for entry in entries:
            # Score based on recency (newer = higher)
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))

            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```

### Section 4: Wire ArchiveStore in startup

**File:** `src/probos/startup/cognitive_services.py`

Add archive store initialization near the Oracle Service wiring (lines 452-466).

Before the Oracle Service initialization, add:

```python
    # AD-524: Ship's Archive — cross-reset knowledge persistence
    archive_store = None
    if config.archive.enabled:
        try:
            from probos.knowledge.archive_store import ArchiveStore
            from probos.storage.sqlite_factory import default_factory

            archive_db_path = config.archive.db_path
            if not archive_db_path:
                # Default: platform-specific archive location outside data_dir
                import sys
                from pathlib import Path
                if sys.platform == "win32":
                    _archive_base = Path.home() / "AppData" / "Local" / "ProbOS" / "archive"
                elif sys.platform == "darwin":
                    _archive_base = Path.home() / "Library" / "Application Support" / "ProbOS" / "archive"
                else:
                    import os
                    _xdg = os.environ.get("XDG_DATA_HOME")
                    _archive_base = (Path(_xdg) / "ProbOS" / "archive" if _xdg
                                     else Path.home() / ".local" / "share" / "ProbOS" / "archive")
                _archive_base.mkdir(parents=True, exist_ok=True)
                archive_db_path = str(_archive_base / "archive.db")

            archive_store = ArchiveStore(archive_db_path, connection_factory=default_factory)
            await archive_store.initialize()
            logger.info("AD-524: ArchiveStore initialized at %s", archive_db_path)
        except Exception as e:
            logger.warning("ArchiveStore failed to start: %s — continuing without", e)
```

Then pass `archive_store` to the Oracle Service constructor:

Also wire shutdown: find the shutdown sequence in `src/probos/startup/shutdown.py`.
Grep for the pattern where other stores are closed (e.g., `records_store`, `event_log`).
Add `await archive_store.close()` in the same block. If the reference isn't available
in the shutdown module, store it on the runtime object (follow existing pattern for
`records_store` or `oracle_service`).

SEARCH:
```python
        oracle_service = OracleService(
            episodic_memory=episodic_memory,
            records_store=records_store,
            knowledge_store=knowledge_store,
            trust_network=trust_network,
            hebbian_router=hebbian_router,
            expertise_directory=expertise_directory,
        )
```

REPLACE:
```python
        oracle_service = OracleService(
            episodic_memory=episodic_memory,
            records_store=records_store,
            knowledge_store=knowledge_store,
            archive_store=archive_store,  # AD-524
            trust_network=trust_network,
            hebbian_router=hebbian_router,
            expertise_directory=expertise_directory,
        )
```

## Tests

**File:** `tests/test_ad524_ships_archive.py`

9 tests:

1. `test_archive_store_initialize` — create `ArchiveStore` with `SQLiteConnectionFactory`,
   call `initialize()`, verify no error and tables exist
2. `test_archive_store_append` — append an entry, verify returned ID > 0
3. `test_archive_store_append_only` — verify no `update()` or `delete()` methods exist
   on `ArchiveStore` (introspect the class)
4. `test_archive_store_search_by_keyword` — append 3 entries with different content,
   search for a keyword in one, verify only that entry is returned
5. `test_archive_store_search_by_category` — append entries with different categories,
   search with category filter, verify filtering works
6. `test_archive_store_count` — append 5 entries, verify `count()` returns 5
7. `test_oracle_service_queries_archive_tier` — create OracleService with an
   `ArchiveStore`, add entries, query, verify results include `source_tier="archive"`
8. `test_oracle_default_tiers_include_archive` — verify default `active_tiers` in
   `query()` includes `"archive"`
9. `test_archive_config_defaults` — verify `ArchiveConfig().enabled` is True,
   `ArchiveConfig().db_path` is empty string

Use `tmp_path` fixture for database files. Use `SQLiteConnectionFactory` directly.

## What This Does NOT Change

- No changes to Ship's Records (AD-434) — records are instance-scoped, archive is cross-reset
- No changes to reset logic — reset still clears data_dir; archive lives outside it
- No automatic archival — entries are manually curated (future: dream consolidation
  can promote to archive, exit notes flow can auto-archive)
- Does NOT add a `/archive` shell command (future enhancement)
- Does NOT add HXI panel for archive browsing (future enhancement)
- Does NOT change episodic memory, trust, or Hebbian storage
- Does NOT add vector/embedding search — uses simple LIKE matching (future: ChromaDB
  collection for archive embeddings)

## Tracking

- `PROGRESS.md`: Add AD-524 as COMPLETE
- `docs/development/roadmap.md`: Update AD-524 status
- `DECISIONS.md`: Record "Archive is append-only SQLite outside data_dir. Oracle Tier 4.
  Simple keyword search initially, vector search deferred."

## Acceptance Criteria

- `ArchiveStore` class exists with `append()`, `search()`, `count()`, `get_recent()`
- No `update()` or `delete()` methods on `ArchiveStore` (append-only invariant)
- `ArchiveStore` uses `ConnectionFactory` protocol (cloud-ready storage pattern)
- `ArchiveConfig` exists in config.py with `enabled` and `db_path` fields
- Oracle Service queries archive as Tier 4
- Archive database location is outside `data_dir` (survives resets)
- All 9 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# No existing archive store
grep -rn "ArchiveStore\|archive_store" src/probos/ → no matches

# Oracle Service location and constructor
grep -n "class OracleService" src/probos/cognitive/oracle_service.py
  43: class OracleService

grep -n "def __init__" src/probos/cognitive/oracle_service.py
  51: __init__(episodic_memory, records_store, knowledge_store,
              trust_network, hebbian_router, expertise_directory)

# Oracle default tiers
grep -n "active_tiers" src/probos/cognitive/oracle_service.py
  92: active_tiers = tiers or ["episodic", "records", "operational"]

# Oracle wiring in startup
grep -n "OracleService" src/probos/startup/cognitive_services.py
  455: from probos.cognitive.oracle_service import OracleService
  456: oracle_service = OracleService(...)

# RecordsConfig pattern (model for ArchiveConfig)
grep -n "class RecordsConfig" src/probos/config.py
  683: class RecordsConfig(BaseModel)

# Cloud-ready storage pattern
grep -n "ConnectionFactory" src/probos/protocols.py
  223: class ConnectionFactory(Protocol)
grep -n "SQLiteConnectionFactory" src/probos/storage/sqlite_factory.py
  10: class SQLiteConnectionFactory

# Data dir resolution (archive must be OUTSIDE this)
grep -n "_default_data_dir" src/probos/__main__.py
  38: def _default_data_dir() → platform-specific data path

# OracleResult definition
grep -n "class OracleResult" src/probos/cognitive/oracle_service.py
  22: @dataclass(frozen=True) OracleResult(source_tier, content, score, metadata, provenance)
```
