# AD-818 v1 — Schema-version table + boot-scan short-circuit

**Status:** Ready — Architect-reviewed (revisions applied)
**Kind:** design → bf (phased)
**Issue:** #751
**Current highest shipped:** AD-839 (Wave 202). AD-818 is the pre-reserved number for issue #751 — this prompt consumes it for the v1 build. Sub-letters AD-818a / AD-818b / AD-818c stay deferred (see §5).

---

## 1. Problem

`startup/cognitive_services.py` runs six episodic-memory migrations at **every boot**
([BF-103, AD-570, AD-570b, AD-584, AD-605](../src/probos/startup/cognitive_services.py#L306-L386), then
[BF-207](../src/probos/startup/cognitive_services.py#L388)). Issue #751 names four structural problems;
this v1 fixes **problem #1 only** (the others are deferred — see §5):

> **Problem #1 — no schema-version table.** Every migration scans the *entire* ChromaDB collection at every
> boot just to discover it has no work to do. Each migration calls
> [`episodic_memory._collection.get(include=[...])`](../src/probos/cognitive/episodic.py#L113) with no
> pagination — a full-collection load — purely to decide whether to act. **The scan itself is the cost
> driver.** On a large store this is the dominant boot cost even when zero episodes need migrating.

The fix: a small SQLite sidecar records *which migration ran at which version*. A migration whose recorded
version matches the current code version is **skipped without scanning the collection at all** — turning an
O(N) full-collection load into an O(1) indexed lookup on every boot after the first.

**Not solved in v1** (deferred, §5): the load-everything OOM inside each migration (AD-818a paginates),
the `probos migrate apply` maintenance verb (AD-818b), and refuse-to-start boot-gating (AD-818c). v1 keeps
today's honest-degrade boot behavior — it only *adds* a short-circuit.

---

## 2. Design

### Sidecar store (mirrors the AD-570b `ParticipantIndex` template exactly)

New module `src/probos/cognitive/schema_versions.py`, modeled on
[`participant_index.py`](../src/probos/cognitive/participant_index.py#L21-L72) (same Cloud-Ready-Storage
`connection_factory` pattern, same `_SCHEMA` + `async start`/`stop` idiom — **do not** call
`aiosqlite.connect` directly except in the `start` fallback, exactly as `ParticipantIndex` does):

```python
from __future__ import annotations
import logging, time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# AD-818: version string per versioned migration. Bump a value when that
# migration's OUTPUT SHAPE changes, so every store re-runs it exactly once.
# ⚠️ BUMP CONTRACT: if you change a migration's output metadata, you MUST bump
# its value here, or every store will SKIP the corrected migration. (The
# data-shape-derived hash from #751 is the explicit AD-818 follow-up seam.)
# BF-207 (hash heal-sweep) is intentionally absent — it is not a one-shot
# schema migration and must keep running every boot.
MIGRATION_VERSIONS: dict[str, str] = {
    "BF-103": "1",
    "AD-570": "1",
    "AD-570b": "1",
    "AD-584": "1",
    "AD-605": "1",
}


class SchemaVersionStore:
    """SQLite sidecar recording which episodic migration ran at which version.

    Lets the boot path skip a migration's full-collection scan when its recorded
    version_hash matches the current code version (AD-818). Mirrors the AD-570b
    ParticipantIndex sidecar pattern for Cloud-Ready Storage.
    """

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_versions (
    migration_id TEXT PRIMARY KEY,
    applied_at REAL NOT NULL DEFAULT 0.0,
    episode_count INTEGER NOT NULL DEFAULT 0,
    version_hash TEXT NOT NULL DEFAULT ''
);
"""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., Any] | None = None,
        db_path: str = "",
    ) -> None:
        self._connection_factory = connection_factory
        self._db_path = db_path
        self._db: Any = None

    async def start(self) -> None: ...   # identical shape to ParticipantIndex.start
    async def stop(self) -> None: ...    # identical shape to ParticipantIndex.stop

    async def get(self, migration_id: str) -> dict | None:
        """Return {migration_id, applied_at, episode_count, version_hash} or None."""

    async def record(
        self, migration_id: str, *, episode_count: int, version_hash: str,
        applied_at: float | None = None,
    ) -> None:
        """INSERT OR REPLACE the row (applied_at defaults to time.time()).

        On any DB error: Tier-2 log-and-degrade (swallow, never propagate) — a
        sidecar write fault must not crash a boot whose migration already
        succeeded; the row simply re-versions next boot."""

    async def is_current(self, migration_id: str, version_hash: str) -> bool:
        """True iff a row exists for migration_id AND its version_hash matches.

        Returns False on any DB error (log-and-degrade → caller runs the
        migration, never crashes boot)."""
```

`is_current` MUST swallow DB errors and return `False` (Tier-2 log-and-degrade): a sidecar fault must
never skip a needed migration *nor* crash boot — it degrades to "run the migration as before."

### Versioned wrapper (augments the existing `_run_one_migration`)

Extend [`_run_one_migration`](../src/probos/startup/cognitive_services.py#L37-L70) with **optional**
keyword params so existing call sites are byte-compatible when omitted:

```python
async def _run_one_migration(
    label, coro_factory, timeout_s, success_template, noop_template,
    *,
    schema_store: Any | None = None,   # AD-818
    migration_id: str | None = None,   # AD-818
    version_hash: str | None = None,   # AD-818
) -> None:
```

Behavior additions (everything else unchanged):
1. **Short-circuit (the value):** if `schema_store` and `migration_id` and `version_hash` are all set AND
   `await schema_store.is_current(migration_id, version_hash)` → `logger.info("%s: schema current
   (version %s) — skipping scan", label, version_hash)` and **return without calling `coro_factory`**.
2. Run the migration exactly as today (start log, `asyncio.wait_for(coro_factory(), timeout=timeout_s)`,
   honest-degrade on `TimeoutError`/`Exception`).
3. **Record only on clean success** (NOT on timeout, NOT on exception): after the `try` succeeds, if
   `schema_store` and `migration_id` and `version_hash` are set →
   `await schema_store.record(migration_id, episode_count=int(migrated or 0), version_hash=version_hash)`.
   Recording-only-on-success is the correctness guarantee: a migration that times out is **not** marked
   current and will retry next boot.

> **⚠️ R1 — PLACEMENT IS LOAD-BEARING.** Put the `await schema_store.record(...)` call as the **final
> statement inside the `try` block**, after the success/noop log lines and the `migrated = await ...`
> assignment, and **above** the `except asyncio.TimeoutError` / `except Exception` clauses. NEVER place it
> after the try/except: on a timeout `migrated` is unbound, so `int(migrated or 0)` would raise
> `UnboundLocalError` and crash boot — the exact failure this wrapper exists to prevent — *and* would
> falsely record a timed-out migration as current.

> **Why record even when `migrated == 0`?** That is the entire point — a no-op completion proves the
> store is at this version, so the next boot can skip the scan. The first AD-818 boot on an
> already-migrated store runs each migration once more (one final full scan, returns 0, records); every
> subsequent boot is O(1). (N2: log this one-time pass as an AD-818 baseline so operators don't read it as
> a loop.)

### Aggregate boot wiring

In `cognitive_services.py`, just after the `_skip_migrations` block
([~L301-L305](../src/probos/startup/cognitive_services.py#L301)) and before the BF-103 block, build the
sidecar (guarded — a build/start failure leaves `schema_store = None`, so every migration runs unversioned
exactly as today):

```python
schema_store = None
if episodic_memory and not _skip_migrations and config.memory.schema_version_tracking:
    try:
        from probos.cognitive.schema_versions import SchemaVersionStore
        schema_store = SchemaVersionStore(db_path=str(data_dir / "schema_versions.db"))
        await schema_store.start()
        logger.info("AD-818: schema-version store started")
    except Exception:
        logger.warning("AD-818: schema-version store start failed (non-fatal); "
                       "migrations will run unversioned", exc_info=True)
        schema_store = None
```

Then pass `schema_store=schema_store, migration_id="BF-103", version_hash=MIGRATION_VERSIONS["BF-103"]`
(and likewise for AD-570, AD-570b, AD-584, AD-605) into each existing `_run_one_migration(...)` call.
**Do NOT** version BF-207 — it stays a plain `await sweep_hash_integrity(...)` every boot.

> **N1 — AD-570b:** the short-circuit skips only the *backfill scan* inside
> `migrate_participant_index`. The `ParticipantIndex` creation + `start()` + `set_participant_index(...)`
> ([cognitive_services.py:330-335](../src/probos/startup/cognitive_services.py#L330)) happen BEFORE the
> `_run_one_migration("AD-570b", ...)` call and must keep running every boot — do not hoist the
> short-circuit above the index lifecycle.

Expose the store for the future maintenance CLI (AD-818b) by mirroring the **AD-838c
`dependency_resolver`** flow exactly:
- [`results.py:116`](../src/probos/startup/results.py#L116) — add field
  `schema_version_store: Any = None  # AD-818` next to `dependency_resolver`.
- [`cognitive_services.py:659`](../src/probos/startup/cognitive_services.py#L659) — add
  `schema_version_store=schema_store,  # AD-818` to the `CognitiveServicesResult(...)` construction next to
  `dependency_resolver=dependency_resolver`.
- [`runtime.py:1853`](../src/probos/runtime.py#L1853) — add
  `self.schema_version_store = cog.schema_version_store  # AD-818` next to
  `self.dependency_resolver = cog.dependency_resolver`.

### Config

Add to the `MemoryConfig` Pydantic model (the model carrying
[`migration_timeout_s` ~L928](../src/probos/config.py#L928)):

```python
schema_version_tracking: bool = False  # AD-818 (#751): skip a migration's
# full-collection scan when its recorded schema version matches. Default False
# (opt-in) for one release of bake time; a grandchild AD flips it True.
```

> **Architect ruling (final): default `False`.** The flag gates a brand-new on-disk persistence surface
> (`schema_versions.db` + its own lifecycle) that deserves one release of opt-in observation regardless of
> logical safety — introduce the mechanism here, flip the default in a named follow-up AD. Do NOT ship
> default `True`; the Builder has no decision to make here.

---

## 3. Build scope (single AD = single commit)

1. **NEW** `src/probos/cognitive/schema_versions.py` — `MIGRATION_VERSIONS` dict + `SchemaVersionStore`
   (full bodies for `start`/`stop`/`get`/`record`/`is_current`, mirroring `ParticipantIndex`; fully typed;
   `is_current` log-and-degrade → `False`).
2. `startup/cognitive_services.py` — extend `_run_one_migration` with the three optional kwargs +
   short-circuit + record-on-success; build the guarded `schema_store`; thread it into the five versioned
   `_run_one_migration` call sites; add `schema_version_store=schema_store` to the result construction.
3. `startup/results.py` — `schema_version_store: Any = None  # AD-818`.
4. `runtime.py` — `self.schema_version_store = cog.schema_version_store  # AD-818`.
5. `config.py` — `MemoryConfig.schema_version_tracking: bool = False`.
6. `startup/shutdown.py` — add a guarded `await runtime.schema_version_store.stop()` teardown (R2),
   mirroring the `attachment_reaper`/`recording_reaper` guarded-stop pattern
   ([shutdown.py:494-504](../src/probos/startup/shutdown.py#L494)):
   ```python
   if getattr(runtime, "schema_version_store", None) is not None:
       try:
           await runtime.schema_version_store.stop()
       except Exception:
           logger.warning("AD-818: schema_version_store.stop() failed", exc_info=True)
   ```
   Unlike `ParticipantIndex` (which `EpisodicMemory.stop()` owns), the schema store has no owner — left
   unstopped, its aiosqlite WAL connection holds `schema_versions.db-wal`/`-shm` locks, a real
   test-isolation hazard on Windows.
7. **NEW** `tests/test_ad818_schema_versions.py` — see §4.
8. Trackers: PROGRESS.md (newest-first) + append an AD-818 v1 BUILD entry to
   `decisions-era-5-unification.md`.

---

## 4. Tests (`tests/test_ad818_schema_versions.py`, pytest + pytest-asyncio)

Use a **real in-memory SQLite** via `connection_factory=lambda: aiosqlite.connect(":memory:")` (NOT
MagicMock at the DB boundary — Phantom-via-MagicMock lesson). For the wrapper tests use a real async stub
migration that flips a `called` flag and returns a configurable int.

`SchemaVersionStore`:
- `start` creates the table (a subsequent `get` works, no error).
- `record` + `get` round-trip returns all four fields; `applied_at` auto-stamps when omitted.
- `get` unknown id → `None`.
- `is_current` → `True` when row exists and hash matches; `False` on hash mismatch; `False` when no row.
- `record` is INSERT-OR-REPLACE (second record for same id overwrites episode_count/version_hash).
- `stop` closes (idempotent / safe when never started).

`_run_one_migration` (import from `cognitive_services`):
- `schema_store=None` → migration always called (today's behavior, byte-identical).
- No prior row → migration called AND a row recorded with the passed version_hash + returned count.
- Recorded row with **matching** version_hash → migration **NOT** called (skip).
- Recorded row with **mismatched** version_hash → migration called + row updated.
- Migration raises → **no** row recorded (retry-next-boot invariant).
- Migration times out (`asyncio.wait_for` → `TimeoutError`) → **no** row recorded.

`MIGRATION_VERSIONS`:
- Contains exactly the five versioned ids (BF-103, AD-570, AD-570b, AD-584, AD-605); BF-207 absent.

Target: ~14 tests.

---

## 5. NOT in scope (deferred sub-letters — do NOT build)

- **AD-818a** — paginate each migration's `_collection.get()` into `limit=`/`offset=` batches wrapped in
  `run_in_executor` (the load-everything OOM fix + makes `wait_for` actually cancellable). This is
  per-migration surgery inside `episodic.py` and is the larger half of #751.
- **AD-818b** — `probos migrate apply [--migration-id X]` maintenance verb (progress UI, cancel,
  resume-from-checkpoint) following the **AD-808** dataclass-plan / dry-run CLI shape
  ([`src/probos/migration/__init__.py`](../src/probos/migration/__init__.py)). The
  `runtime.schema_version_store` exposed here is its hook.
- **AD-818c** — refuse-to-start boot guard (detect missing/outdated schema versions, REFUSE to boot with a
  clear error suggesting `probos migrate`). Behavior change with brick-the-boot risk — deliberately last.
- No `ui/` changes. No change to the existing `PROBOS_SKIP_EPISODIC_MIGRATIONS` env hatch. No change to
  any migration function body in `episodic.py`. No change to `_MIGRATION_BATCH_SIZE`.

---

## 6. Acceptance criteria

1. `SchemaVersionStore` exists, fully typed, mirrors the `ParticipantIndex` sidecar pattern
   (`connection_factory` Cloud-Ready Storage), `is_current` log-and-degrades to `False`.
2. `_run_one_migration` short-circuits on matching version and records **only on clean success**; with the
   new kwargs omitted it is byte-compatible with today.
3. The five versioned migrations are threaded through the store; BF-207 still runs every boot; the
   `PROBOS_SKIP_EPISODIC_MIGRATIONS` hatch and `_skip_migrations` guard still win.
4. Store-build failure / `schema_version_tracking=False` → migrations run unversioned exactly as today
   (no regression, never crashes boot).
5. `runtime.schema_version_store` is exposed via the AD-838c result→runtime pattern, and a guarded
   `stop()` teardown is wired in `shutdown.py` (R2).
6. `tests/test_ad818_schema_versions.py` passes; the gate (`pytest tests/ -q -n 0`, or the AD-838
   blast-radius subset if the full gate is impractically long) shows no regressions.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 7. Verified against the live codebase (anchors — re-confirm before editing)

- `_run_one_migration` async wrapper: [cognitive_services.py:37-70](../src/probos/startup/cognitive_services.py#L37).
  Honest-degrade on `TimeoutError`/`Exception`, returns `None`, `migrated` is the awaited int.
- Migration call sites: [cognitive_services.py:306-386](../src/probos/startup/cognitive_services.py#L306)
  (BF-103, AD-570, AD-570b, AD-584, AD-605) + plain [BF-207 @L388](../src/probos/startup/cognitive_services.py#L388).
  `data_dir` is in scope (AD-570b uses `data_dir / "participant_index.db"`). `_skip_migrations` env hatch
  @[~L301](../src/probos/startup/cognitive_services.py#L301).
- Sidecar template: [participant_index.py:21-90](../src/probos/cognitive/participant_index.py#L21)
  (`connection_factory`/`db_path` ctor, `_SCHEMA`, `async start`/`stop`).
- Migration fns live in [episodic.py](../src/probos/cognitive/episodic.py) (BF-103 @92, AD-570 @187,
  AD-584 @285, AD-570b/`migrate_participant_index` @371, AD-605 @416, BF-207/`sweep_hash_integrity` @508);
  all use full `_collection.get(...)`. `_MIGRATION_BATCH_SIZE = 2000` @[L57](../src/probos/cognitive/episodic.py#L57)
  is for upsert chunking, **not** read pagination. (v1 does NOT touch these bodies.)
- Config model carrying `migration_timeout_s` (`Field(default=300.0, ge=10.0, le=3600.0)`):
  [config.py:928](../src/probos/config.py#L928). Add the new flag in the same model.
- AD-838c result→runtime pattern to mirror: [results.py:116](../src/probos/startup/results.py#L116),
  [cognitive_services.py:659](../src/probos/startup/cognitive_services.py#L659),
  [runtime.py:1853](../src/probos/runtime.py#L1853).
- Shutdown teardown precedent (R2): guarded `*.stop()` calls in
  [shutdown.py:494-504](../src/probos/startup/shutdown.py#L494); `EpisodicMemory.stop()` owns
  `participant_index.stop()` at [episodic.py:958](../src/probos/cognitive/episodic.py#L958), itself wired
  at [shutdown.py:292](../src/probos/startup/shutdown.py#L292).
- AD-808 (CLI shape ref for the deferred AD-818b only):
  [src/probos/migration/__init__.py](../src/probos/migration/__init__.py) — cross-ecosystem import tool,
  unrelated to episodic migrations.
- Highest shipped AD: AD-839 (PROGRESS.md). AD-818 is the pre-reserved #751 number.
