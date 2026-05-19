# AD-742f — Per-agent vision working memory persistence across restart

**Wave:** 175
**Closes:** #674
**Status:** drafting → GATE 1
**Dependencies:** AD-733a (VisionWorkingMemory shipped), AD-731 (AttachmentStore SHA refs).
**Estimated tests:** +10 pytest, 0 vitest.
**License posture:** 0-line diff (no new deps; uses stdlib `sqlite3` via existing `aiosqlite`).

---

## Problem

`VisionWorkingMemory` is in-memory only. Restart blanks every observer's
8-entry ring buffer. Captain's most common use case — "what was I wearing
earlier today?" / "describe the thing on the desk you saw last hour" —
breaks across restart. AD-541b anchored episodes ARE persisted (chroma), but
those are summarized long-term memory; the per-agent ring buffer is the hot
prompt-context substrate and is the one VisionWorkingMemory.render_for_prompt
actually injects.

Forward marker file: `src/probos/perception/working_memory.py:4` already
references AD-742f.

## Solution

Add SQLite persistence at `data/perception_wm.db`. Per-agent ring buffer
auto-loads on `VisionWorkingMemory.__init__` and async-writes on every
`append`. Eviction-on-cap deletes the oldest row for that agent_id. Honest-
degrade: if the DB is unavailable or schema migration fails, log WARNING
and operate as the existing in-memory ring (BF-274-grade fallback).

Default: ON (`perception.wm_persistence_enabled=True`). Footprint is tiny
(~200 B/observation, capped at `working_memory_capacity` per agent × N agents).
Operator opt-out by flipping the flag (hot-reload).

## Threat model

- Descriptions can mention people, objects, locations — same sensitivity tier
  as `data/chroma.sqlite3` (episodic memory). Local-only, never federation-
  synced.
- AD-731 invariant preserved: descriptions are text (max 400 chars per
  AD-733a truncation). **No image bytes** stored in this DB — only SHA refs
  pointing at AttachmentStore.
- Subject identity is whatever AD-742b resolved at the time ("captain" /
  "unknown" / "other"). No PII beyond what was already in the in-memory ring.
- File at `data/perception_wm.db` — covered by existing `.gitignore` for
  `data/*.db`.

---

## Section 0: Configuration (additive, hot-reload)

### File: `src/probos/config.py`

Add to `PerceptionConfig` (anchor after `working_memory_capacity` at line 2005):

```
===SEARCH===
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
        description="Per-agent vision working memory ring buffer size.",
    )
    vision_tier: str = Field(default="vision",
===REPLACE===
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
        description="Per-agent vision working memory ring buffer size.",
    )
    wm_persistence_enabled: bool = Field(default=True,
        description="AD-742f: persist VisionWorkingMemory rings to data/perception_wm.db so Captain's per-agent visual history survives restart. Set False to operate in-memory only (legacy behavior).",
    )
    vision_tier: str = Field(default="vision",
===END REPLACE===
```

### File: `src/probos/perception/__init__.py`

Register the field in the Settings UI (append a FieldDescriptor near the
existing perception fields):

```
===SEARCH===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
===REPLACE===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.wm_persistence_enabled",
            "Persist vision working memory",
            "bool",
            description="AD-742f: load + write the per-agent vision working-memory ring to data/perception_wm.db so Captain's recent-frame recall survives restart. Disable for in-memory-only operation.",
            hot_reload=True,
        ),
===END REPLACE===
```

> Note: hot-reload toggles the WRITE path only — already-loaded rings stay
> intact. Flipping enabled→disabled stops new writes; flipping back on
> re-enables writes from that point. Restart still required to re-LOAD
> from disk after a long offline-only stretch.

---

## Section 1: SQLite store module

### New file: `src/probos/perception/wm_store.py`

```python
"""AD-742f: SQLite persistence for VisionWorkingMemory ring buffers.

Tier-2 honest-degrade: every method swallows DB exceptions, logs WARNING,
and lets the caller operate in-memory only. The store NEVER raises into the
VisionWorkingMemory hot path — frame describe must not fail because of a
DB lock.

AD-731 invariant: descriptions are text; SHA refs point at AttachmentStore.
NO image bytes in this DB.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.perception.working_memory import VisionObservation

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    attachment_ref  TEXT NOT NULL,
    description     TEXT NOT NULL,
    novelty_score   REAL NOT NULL,
    subject_identity TEXT NOT NULL DEFAULT 'unknown',
    session_id      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vision_observations_agent_ts
    ON vision_observations (agent_id, timestamp);
"""


class WorkingMemoryStore:
    """Synchronous sqlite3-backed ring persistence.

    Sync rather than aiosqlite because VisionWorkingMemory.append is called
    from synchronous WM code; we don't have an event loop handle there. The
    write path is short (<1 ms) and protected by a module-level lock so
    multiple agents writing concurrently don't fight the connection.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = Lock()
        self._available = False
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
            self._available = True
            logger.info("AD-742f: vision WM store ready at %s", self._db_path)
        except Exception:
            logger.warning(
                "AD-742f: WM store init failed; perception WM will be in-memory only",
                exc_info=True,
            )

    @property
    def available(self) -> bool:
        return self._available

    def load_for_agent(self, agent_id: str, *, capacity: int) -> list["VisionObservation"]:
        """Newest-last (deque insert order) up to ``capacity`` rows."""
        if not self._available:
            return []
        from probos.perception.working_memory import VisionObservation
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "SELECT timestamp, attachment_ref, description, novelty_score, "
                    "subject_identity, session_id FROM vision_observations "
                    "WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (agent_id, int(capacity)),
                )
                rows = list(cursor.fetchall())
        except Exception:
            logger.warning(
                "AD-742f: load_for_agent(%s) failed; returning empty",
                agent_id, exc_info=True,
            )
            return []
        # Reverse so the deque receives oldest-first → newest-last.
        rows.reverse()
        return [
            VisionObservation(
                timestamp=float(r[0]),
                attachment_ref=str(r[1]),
                description=str(r[2]),
                novelty_score=float(r[3]),
                subject_identity=str(r[4]),
                session_id=str(r[5]),
            )
            for r in rows
        ]

    def append(self, agent_id: str, obs: "VisionObservation", *, capacity: int) -> None:
        """Insert + evict-oldest-beyond-capacity. Best-effort."""
        if not self._available:
            return
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO vision_observations "
                    "(agent_id, timestamp, attachment_ref, description, "
                    "novelty_score, subject_identity, session_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        agent_id,
                        float(obs.timestamp),
                        str(obs.attachment_ref),
                        str(obs.description),
                        float(obs.novelty_score),
                        str(obs.subject_identity),
                        str(obs.session_id),
                    ),
                )
                # Evict any rows beyond capacity for THIS agent. Keep the
                # newest ``capacity`` by timestamp; delete the rest.
                conn.execute(
                    "DELETE FROM vision_observations WHERE id IN ("
                    "  SELECT id FROM vision_observations WHERE agent_id = ? "
                    "  ORDER BY timestamp DESC LIMIT -1 OFFSET ?"
                    ")",
                    (agent_id, int(capacity)),
                )
                conn.commit()
        except Exception:
            logger.warning(
                "AD-742f: append(%s) failed; in-memory ring still updated",
                agent_id, exc_info=True,
            )

    def clear_for_agent(self, agent_id: str) -> None:
        """Test helper + operator reset."""
        if not self._available:
            return
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "DELETE FROM vision_observations WHERE agent_id = ?",
                    (agent_id,),
                )
                conn.commit()
        except Exception:
            logger.warning(
                "AD-742f: clear_for_agent(%s) failed", agent_id, exc_info=True,
            )
```

---

## Section 2: VisionWorkingMemory integration

### File: `src/probos/perception/working_memory.py`

```
===SEARCH===
class VisionWorkingMemory:
    """Thread-safe per-agent ring buffer. One instance per agent_id per runtime."""

    def __init__(self, *, capacity: int = 8) -> None:
        self._buf: deque[VisionObservation] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(self, obs: VisionObservation) -> None:
        with self._lock:
            self._buf.append(obs)
===REPLACE===
class VisionWorkingMemory:
    """Thread-safe per-agent ring buffer. One instance per agent_id per runtime.

    AD-742f: when a ``store`` + ``agent_id`` are provided, the ring is
    auto-loaded from SQLite on construction and every ``append`` is
    mirrored to disk (best-effort, honest-degrade on failure).
    """

    def __init__(
        self,
        *,
        capacity: int = 8,
        store: object | None = None,
        agent_id: str = "",
    ) -> None:
        self._buf: deque[VisionObservation] = deque(maxlen=capacity)
        self._lock = Lock()
        self._store = store
        self._agent_id = str(agent_id)
        # AD-742f: hydrate ring from disk if a store is wired.
        if self._store is not None and self._agent_id:
            try:
                rows = self._store.load_for_agent(self._agent_id, capacity=capacity)
                for obs in rows:
                    self._buf.append(obs)
            except Exception:
                # Honest-degrade: store reported unavailable or row decode failed.
                # Tier-2 — never raise from __init__.
                pass

    def append(self, obs: VisionObservation) -> None:
        with self._lock:
            self._buf.append(obs)
        # AD-742f: best-effort persist. Outside the lock so a slow DB write
        # doesn't block in-memory reads.
        if self._store is not None and self._agent_id:
            try:
                self._store.append(self._agent_id, obs, capacity=self._buf.maxlen or 8)
            except Exception:
                pass
===END REPLACE===
```

---

## Section 3: Consumer factory wiring

### File: `src/probos/perception/consumer.py`

Replace the module-scoped factory to thread the store through:

```
===SEARCH===
# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
# Module-scoped because the consumer is runtime-singleton — one runtime
# owns one camera and dispatches to N agents.
_WORKING_MEMORIES: dict[str, Any] = {}  # agent_id -> VisionWorkingMemory


def get_or_create_working_memory(agent_id: str, *, capacity: int = 8) -> Any:
    """Return the VisionWorkingMemory for an agent, creating on first access."""
    from probos.perception.working_memory import VisionWorkingMemory
    if agent_id not in _WORKING_MEMORIES:
        _WORKING_MEMORIES[agent_id] = VisionWorkingMemory(capacity=capacity)
    return _WORKING_MEMORIES[agent_id]


def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry."""
    _WORKING_MEMORIES.clear()
===REPLACE===
# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
# Module-scoped because the consumer is runtime-singleton — one runtime
# owns one camera and dispatches to N agents.
_WORKING_MEMORIES: dict[str, Any] = {}  # agent_id -> VisionWorkingMemory

# AD-742f: optional shared store wired at runtime startup. None = legacy
# in-memory-only behavior (BF-274 fallback path).
_WM_STORE: Any = None


def set_working_memory_store(store: Any) -> None:
    """AD-742f: install the shared SQLite store. None disables persistence."""
    global _WM_STORE
    _WM_STORE = store


def get_or_create_working_memory(agent_id: str, *, capacity: int = 8) -> Any:
    """Return the VisionWorkingMemory for an agent, creating on first access."""
    from probos.perception.working_memory import VisionWorkingMemory
    if agent_id not in _WORKING_MEMORIES:
        _WORKING_MEMORIES[agent_id] = VisionWorkingMemory(
            capacity=capacity,
            store=_WM_STORE,
            agent_id=agent_id,
        )
    return _WORKING_MEMORIES[agent_id]


def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry AND the store handle."""
    global _WM_STORE
    _WORKING_MEMORIES.clear()
    _WM_STORE = None
===END REPLACE===
```

---

## Section 4: Startup wiring

### File: `src/probos/startup/finalize.py`

Anchor: the existing `VisionConsumer` block at ~line 4017. Insert the store
construction BEFORE the consumer is constructed so the first
`get_or_create_working_memory` call in `register_observer`'s downstream
already sees a populated `_WM_STORE`:

```
===SEARCH===
        if (
            _perception_cfg is not None
            and _perception_cfg.enabled
            and getattr(_perception_cfg, "vision_consumer_enabled", False)
        ):
            from probos.perception.consumer import VisionConsumer

            consumer = VisionConsumer(
===REPLACE===
        if (
            _perception_cfg is not None
            and _perception_cfg.enabled
            and getattr(_perception_cfg, "vision_consumer_enabled", False)
        ):
            from probos.perception.consumer import VisionConsumer

            # AD-742f: wire the shared SQLite WM store before observers register.
            if getattr(_perception_cfg, "wm_persistence_enabled", True):
                try:
                    from pathlib import Path
                    from probos.perception.consumer import set_working_memory_store
                    from probos.perception.wm_store import WorkingMemoryStore
                    _data_dir = Path(getattr(runtime, "data_dir", None) or "data")
                    _wm_store = WorkingMemoryStore(_data_dir / "perception_wm.db")
                    if _wm_store.available:
                        set_working_memory_store(_wm_store)
                        runtime.vision_wm_store = _wm_store
                        logger.info("AD-742f: vision WM persistence active")
                    else:
                        runtime.vision_wm_store = None
                except Exception:
                    logger.warning(
                        "AD-742f: WM store wiring failed; in-memory-only ring",
                        exc_info=True,
                    )
                    runtime.vision_wm_store = None
            else:
                runtime.vision_wm_store = None

            consumer = VisionConsumer(
===END REPLACE===
```

---

## Section 5: Tests

### New file: `tests/test_ad742f_wm_persistence.py`

Use real `WorkingMemoryStore` over a `tmp_path` SQLite file (no MagicMock —
BF-287). Test cases:

1. `test_store_init_creates_schema` — connect to a fresh db_path, verify
   `vision_observations` table exists via `PRAGMA table_info`.
2. `test_append_persists_and_loads` — store an observation, construct a new
   `VisionWorkingMemory` with the same store + agent_id, confirm `entries()`
   returns the same observation.
3. `test_load_respects_capacity_cap` — insert 12 rows directly via the
   store, construct a WM with capacity=8, confirm 8 rows loaded (newest 8 by
   timestamp).
4. `test_append_evicts_oldest_beyond_capacity` — append 12 observations
   one-by-one through the WM (capacity=8), then construct a fresh WM and
   verify only the newest 8 are loaded.
5. `test_clear_for_agent_isolated` — append for two agent_ids, clear one,
   verify the other's rows survive.
6. `test_unavailable_store_honest_degrade` — point the store at an
   unwritable path (`/nonexistent/path/probos.db` or a read-only file under
   tmp_path), assert `store.available is False` AND that a WM constructed
   with this store still functions as an in-memory ring (append + entries
   work, no exception).
7. `test_wm_without_store_in_memory_only` — construct `VisionWorkingMemory`
   with `store=None`, confirm append + entries work and no `data/*.db` file
   is created.
8. `test_ad731_invariant_no_image_bytes` — inspect the schema row-by-row,
   assert no column has type `BLOB`. Descriptions are TEXT, refs are TEXT.
9. `test_consumer_factory_threads_store` — call `set_working_memory_store`
   with a fixture store, call `get_or_create_working_memory("agent-x")`,
   assert the returned WM's `_store` is the fixture instance.
10. `test_factory_reset_clears_store_handle` — call
    `reset_working_memories_for_tests`, assert subsequent
    `get_or_create_working_memory` builds WMs with `store=None`.

### Acceptance: `pytest tests/test_ad742f_wm_persistence.py -v -n 0` → 10 passed.

---

## What this does NOT change

- AD-541b chroma episodic memory — unchanged. Persistence is additive, not
  replacement. Chroma stays the long-term recall path.
- AD-731 AttachmentStore — unchanged. SHA refs only; no image bytes touch
  `perception_wm.db`.
- AD-733c-2 PerceptionModeController — unchanged. Mode transitions do not
  touch WM persistence.
- BF-308 hot-reload setters — unchanged. WM is data, not a strategy knob.
- Federation — unchanged. `perception_wm.db` is local-only (not in the
  federation-sync list). Cross-host persistence = AD-742f-1 forward marker.

## Forward markers

- **AD-742f-1** — Cross-host federation of WM rows (Captain-on-laptop +
  Captain-on-desktop see the same recall). Requires a sync protocol +
  conflict resolution; out of scope tonight.
- **AD-742f-2** — TTL-based pruning of old rows (the cap-evict only
  removes by per-agent count, not by age — long-lived sessions retain rows
  forever within the cap, but daily rotation may be desirable for privacy).

File both as GitHub issues at wave close.

---

## AD-722c-3 forward-marker triggers

None new. WM persistence is well-scoped.

## License posture

0-line diff on all 5 license files. Uses stdlib `sqlite3` (PSF license,
already absorbed via Python itself). No new pip / npm deps.

## Acceptance criteria

- 10 new pytest in `tests/test_ad742f_wm_persistence.py` green at `-n 0`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` net-green vs baseline.
- `pytest tests/test_ad733a_vision_consumer.py -v -n 0` still passes (proves
  the store-None fallback path is intact for existing tests).
- After a runtime restart with `perception.enabled=True`, the previous
  session's `wm.entries()` for the Captain's main agent is non-empty
  (manual verification step in build report).
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-18)

```
grep -n "class VisionWorkingMemory" src/probos/perception/working_memory.py
  32: class VisionWorkingMemory:

grep -n "def get_or_create_working_memory" src/probos/perception/consumer.py
  44: def get_or_create_working_memory(agent_id: str, *, capacity: int = 8) -> Any:

grep -n "_WORKING_MEMORIES" src/probos/perception/consumer.py
  39: _WORKING_MEMORIES: dict[str, Any] = {}
  46:     if agent_id not in _WORKING_MEMORIES:
  47:         _WORKING_MEMORIES[agent_id] = VisionWorkingMemory(capacity=capacity)
  48:     return _WORKING_MEMORIES[agent_id]
  52: def reset_working_memories_for_tests() -> None:

grep -n "working_memory_capacity" src/probos/config.py
  2005:     working_memory_capacity: int = Field(default=8, ge=1, le=64,

grep -n "VisionConsumer(" src/probos/startup/finalize.py
  4017:             consumer = VisionConsumer(

grep -n "SQLiteConnectionFactory\|aiosqlite" src/probos/storage/sqlite_factory.py
  4: import aiosqlite
  10: class SQLiteConnectionFactory:

ls data/*.db
  data/events.db, data/working_memory.db, ... (pattern confirmed)
```

The new `perception_wm.db` slots into the existing `data/*.db` convention.
The `WorkingMemoryStore` uses stdlib `sqlite3` (not aiosqlite) because the
hot path is `VisionWorkingMemory.append`, which is synchronous — adding a
new async dependency there would force every observer write into a
`run_in_executor` round-trip for no gain on <1 ms inserts.
