# AD-456d v1 — Security Infrastructure: AuditLog SQLite Persistence

**Status:** ready
**Dependencies:** AD-456 v1 (`AuditLog`, `AuditEntry`, `verify_chain`, `runtime.audit_log` — all shipped Wave 7); AD-466 (`protocols.ConnectionFactory` cloud-ready storage abstraction — shipped); AD-622 (`ClearanceGrantStore` — sibling pattern for SQLite + WAL/busy_timeout/synchronous PRAGMA shape); AD-680 (`runtime.emit_event` public — shipped); AD-686b (`OracleService.attach_semantic_layer` — sibling pattern for `attach_*` setter)
**Estimated tests:** 14 new (1 new test file `tests/test_ad456d_audit_log_persistence.py`)
**Closes:** GH issue #400

---

## Problem

`AuditLog` (`src/probos/security/audit.py`, AD-456 v1, Wave 7) ships an append-only, SHA-256 hash-chained, in-memory record with `verify_chain()` tamper detection. The module's own docstring contracts the gap (`audit.py:1-6`):

```
"""AD-456: AuditLog -- append-only hash-chained record.

v1 in-memory only. Each entry includes the SHA-256 of the prior entry
(hash chain). Tamper detection via ``verify_chain()``. Persistence to SQLite
deferred to AD-456d.
"""
```

The roadmap entry (`docs/development/roadmap.md:4148`) names AD-456d:

> "AD-456d: Security Infrastructure — AuditLog SQLite Persistence — Persist inference audit log entries to SQLite for post-incident forensic review. v1 audit layer logs to Python logger only — entries lost on restart. Must use cloud-ready storage abstraction. Same persistence pattern as AD-635b (clinical audit ring)."

(The "logs to Python logger only" line is imprecise — actual v1 maintains a SHA-256-chained `list[AuditEntry]` in memory and emits `AUDIT_RECORDED`. The entries-lost-on-restart consequence is correct; the cause is in-memory storage, not logger-only output. v1 also has zero production callers of `AuditLog.append()` — all 4 callers are tests in `test_ad456_security_infrastructure.py::TestAuditLog`. AD-456d ships the persistence seam so future caller integration lands on durable storage from day one.)

The cloud-ready abstraction is `protocols.ConnectionFactory` (AD-466), already consumed by `ClearanceGrantStore` (AD-622, `clearance_grants.py:17`), `ArchiveStore` (AD-524, `knowledge/archive_store.py:19`), `CognitiveJournal` (AD-431), `SQLiteKnowledgeEdgeStore` (AD-687), and the rest of the SQLite-backed storage modules.

This AD plumbs the seam:

```
AuditLog (in-memory chain — unchanged)
    │
    ├── _persistence: AuditLogPersistence | None    # NEW: optional persistence seam
    ├── _pending_writes: set[asyncio.Task]          # NEW: fire-and-forget task tracking
    ├── attach_persistence(persistence)             # NEW: setter (AD-686b mirror)
    └── append(...)
            │
            ├── existing in-memory append + AUDIT_RECORDED emit   # unchanged
            └── if _persistence and loop running:                  # NEW
                    task = loop.create_task(_persistence.persist_entry(entry))
                    _pending_writes.add(task)
                    task.add_done_callback(_pending_writes.discard)

AuditLogPersistence (NEW)
    ├── __init__(*, db_path, connection_factory)    # required kwargs
    ├── async start()                               # connect + WAL/busy/sync + schema
    ├── async stop()                                # close (NOT wired in v1 — AD-456d-1)
    ├── async persist_entry(entry)                  # INSERT + commit + AUDIT_PERSISTED emit
    ├── async load_entries() -> list[AuditEntry]    # SELECT * ORDER BY sequence ASC
    └── async count() -> int                        # SELECT COUNT(*) (testability)

startup/finalize.py wiring (NEW if-block, after existing AD-456 AuditLog block)
    construct → start → load → extend → verify (warn-only) → attach_persistence → set runtime attr
```

`v1 ships the per-append fire-and-forget pattern` — one `loop.create_task` per `append()`, tracked via `_pending_writes` set per copilot-instructions Async Discipline rule. Batched persist queue (single drain task vs per-append create_task), shutdown-flush hook (`runtime.audit_log_persistence.stop()` at process exit), tamper-on-rehydrate Captain-alert path, default-flip of `audit_persistence_enabled`, retention/TTL policy, HXI inspection surface, and commercial overlays (Postgres / cloud audit-storage adapters via `ConnectionFactory` extension point already shipped at AD-466) are deferred to AD-456d-2 / -1 / -3 / -4 / -6 / -7 / -5 *(Commercial)* respectively.

## Solution

v1 ships:

1. **`AuditLog._persistence: "AuditLogPersistence | None" = None`** — additive dataclass field. Default None preserves AD-456 contract; existing 4 tests in `test_ad456_security_infrastructure.py::TestAuditLog` continue to pass without modification.

2. **`AuditLog._pending_writes: set[asyncio.Task[Any]] = field(default_factory=set)`** — additive dataclass field. Holds references to in-flight persist tasks per copilot-instructions Async Discipline rule ("Always hold a reference to tasks created with `asyncio.create_task()`. Fire-and-forget tasks silently swallow exceptions and can be garbage collected. Store in a set or instance variable and remove on completion."). Each task adds itself via `set.add(task)` and registers `task.add_done_callback(self._pending_writes.discard)` — bounded set, no leak.

3. **`AuditLog.attach_persistence(persistence: "AuditLogPersistence") -> None`** — public setter. Mirrors `OracleService.attach_semantic_layer` shape from AD-686b (Wave 50). Pure setter; no other side effects.

4. **`AuditLog.append()` extended with fire-and-forget persist hook.** After in-memory append + `AUDIT_RECORDED` emit (both unchanged), if `_persistence is not None`, attempt to schedule a persist task. Loop probe: `try: loop = asyncio.get_running_loop(); except RuntimeError: logger.debug(...); return entry`. With a running loop: `task = loop.create_task(self._persistence.persist_entry(entry))`, `self._pending_writes.add(task)`, `task.add_done_callback(self._pending_writes.discard)`. Sync return path is unchanged — `append()` always returns the `AuditEntry` immediately.

5. **`AuditLogPersistence`** — new module-level class in `audit.py` (defined AFTER `AuditLog`). Cloud-ready via injected `connection_factory: ConnectionFactory`. API:
   - `__init__(self, *, db_path: str, connection_factory: ConnectionFactory)` — both kwargs REQUIRED (mirrors `ArchiveStore` shape, `knowledge/archive_store.py:63`).
   - `async start()` — `connect → PRAGMA WAL/busy_timeout/synchronous → executescript(_SCHEMA) → commit`. Mirrors `ClearanceGrantStore.start()` exactly (`clearance_grants.py:64-72`).
   - `async stop()` — close connection. Defined but NOT wired in v1 production runtime shutdown (deferred to AD-456d-1). Tests call it directly.
   - `async persist_entry(entry: AuditEntry)` — single-row INSERT + commit + emit `AUDIT_PERSISTED`. Wrapped in `try/except Exception: logger.warning(..., exc_info=True)` per copilot-instructions tier-2 log-and-degrade rule. Caller is a fire-and-forget task; an unhandled exception would print an asyncio warning to stderr and the task object's `.exception()` would carry the error silently from the sync `append()` caller's perspective. The warning log is the visible failure signal.
   - `async load_entries() -> list[AuditEntry]` — `SELECT * ... ORDER BY sequence ASC`. Returns `list[AuditEntry]` ordered for chain rehydration. ORDER BY required — without it, SQLite is permitted to return rows in any order, which would shuffle the prior_hash chain.
   - `async count() -> int` — `SELECT COUNT(*)` for testability.
   - `emit_event: Any | None = None` — optional kwarg on `__init__`; if set, `persist_entry` emits `AUDIT_PERSISTED` via this hook. Mirrors `AuditLog.emit_event` shape.

6. **SQL schema (`_SCHEMA`)** — module-level constant in `audit.py`. 6 columns mirroring `AuditEntry` dataclass:
   - `sequence INTEGER PRIMARY KEY` (already monotonic per `len(self.entries)`-based assignment)
   - `timestamp REAL NOT NULL`
   - `category TEXT NOT NULL`
   - `detail TEXT NOT NULL`
   - `prior_hash TEXT NOT NULL`
   - `entry_hash TEXT NOT NULL UNIQUE` (already unique per SHA-256-of-prior-hash chain semantics)
   - Plus `CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);` for AD-456d-7 future range queries.

7. **`EventType.AUDIT_PERSISTED`** — single new enum value. Inserted immediately after `CREDENTIAL_TIER_DENIED` (line 213) — adjacent to the AD-456 / AD-456b / AD-456c security-infra event cluster.

8. **`SecurityInfraConfig.audit_persistence_enabled: bool = False`** — Convention #14 + #3 + Wave 55 / Wave 56 sibling pattern: default False on the transitional flag. AD-456d-4 flips default to True once AD-456d-1 (shutdown flush) lands.

9. **`SecurityInfraConfig.audit_persistence_filename: str = "audit_log.db"`** — mirrors `secrets_store_filename` shape (AD-456 v1, `config.py:1457`). Operator-configurable filename under `runtime.data_dir`.

10. **`startup/finalize.py` wiring** — single new if-block inserted IMMEDIATELY AFTER the existing AD-456 AuditLog block (lines 1293-1297) and BEFORE the AD-456b RuntimeSandbox block. Sequence:
    ```
    construct AuditLogPersistence(db_path=..., connection_factory=SQLiteConnectionFactory(), emit_event=runtime.emit_event)
    await persistence.start()
    loaded = await persistence.load_entries()
    if loaded:
        runtime.audit_log.entries.extend(loaded)
        if not runtime.audit_log.verify_chain():
            logger.warning("AD-456d: AuditLog chain verification FAILED on rehydrate (tamper or corruption suspected; AD-456d-3 will add Captain alert path)")
    runtime.audit_log.attach_persistence(persistence)
    runtime.audit_log_persistence = persistence
    logger.info("AD-456d: AuditLog persistence wired (db=%s, rehydrated=%d)", path, len(loaded))
    ```
    Whole block wrapped in `try/except Exception: logger.warning(..., exc_info=True)` — boot continues with `runtime.audit_log_persistence = None` on any failure. Mirrors the existing AD-456 CredentialStore extension block (`finalize.py:1252-1267`) try/except shape exactly.

`tokens_used`-style backwards compatibility: every existing AD-456 test (`test_ad456_security_infrastructure.py`), every existing AD-456b test (`test_ad456b_runtime_sandboxing.py`), every existing AD-456c test (`test_ad456c_per_tier_credentials.py`), every existing finalize test continues to function. No symbol is removed; no signature is changed (additive `attach_persistence` method is a new public member). New `_persistence` field defaults None; new `_pending_writes` defaults empty set; new `audit_persistence_enabled` config defaults False; new `audit_persistence_filename` config defaults to a sensible name. Existing `AuditLog(emit_event=emit)` and `AuditLog()` constructions behave identically to today.

### Scope

| Component | Status |
|---|---|
| `AuditLog._persistence` + `_pending_writes` dataclass fields | EDIT (additive) |
| `AuditLog.attach_persistence` setter method | EDIT (additive) |
| `AuditLog.append` fire-and-forget persist hook | EDIT (additive — sync return path unchanged) |
| `AuditLogPersistence` class (start/stop/persist_entry/load_entries/count) | NEW (module-level in `audit.py`) |
| Module-level `_SCHEMA` constant | NEW (in `audit.py`) |
| `EventType.AUDIT_PERSISTED` | NEW |
| `SecurityInfraConfig.audit_persistence_enabled` | NEW |
| `SecurityInfraConfig.audit_persistence_filename` | NEW |
| `startup/finalize.py` `AuditLogPersistence` wiring (1 if-block) | EDIT (additive) |
| `runtime.audit_log_persistence` attribute (greenfield) | NEW (set in finalize) |
| `tests/test_ad456d_audit_log_persistence.py` (14 tests) | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Shutdown-flush hook** (`runtime.audit_log_persistence.stop()` wired into runtime shutdown sequence). v1 sets `runtime.audit_log_persistence` so the future hook can be a one-line addition; v1 ships start + persist_entry + load_entries + a stop() method that exists but is unwired in production runtime shutdown. Deferred to AD-456d-1 (paired with similar shutdowns for ClearanceGrantStore, CognitiveJournal, etc.).
- **Batched persist queue + drain loop.** The obvious perf optimisation (single drain task that flushes a queue) introduces a state machine (queue depth, drain interval, backpressure semantics) that's substantial v1 risk for a feature whose current production caller-base is ZERO (all 4 existing callers are tests). v1 ships per-append `create_task`; AD-456d-2 layers a queue when a real caller surfaces and a perf signal appears.
- **Tamper-on-rehydrate Captain-alert path.** v1 logs WARNING on `verify_chain() == False` after rehydrate but does NOT block boot, emit a tamper EventType, or route to the Counselor / Captain alert paths. Boot-failing on tamper would mean a single corrupted row makes the whole runtime unstartable; that's a worse failure mode than a noisy log + observer. AD-456d-3 will add `EventType.AUDIT_TAMPER_DETECTED` + Captain-alert routing once the Counselor surface is ready.
- **Default-flip of `audit_persistence_enabled` to True.** v1 default False per Convention #14 + Convention #3. Deferred to AD-456d-4 once AD-456d-1 (shutdown flush) lands and a fleet-wide upgrade rehearsal confirms no rehydrate-tamper false positives.
- **Retention policy (TTL or row cap) + archival to ShipsArchive.** v1 ships unbounded growth on a single SQLite file; SQLite handles GB-scale comfortably for the duration of v1's expected production caller-base. AD-456d-6 will add a retention policy + archival hook once a real caller surfaces.
- **HXI inspection surface** (`/audit list`, `/audit verify`, `/audit since <ts>` shell commands). Deferred to AD-456d-7.
- **Commercial overlays** (*Postgres / cloud audit-storage adapters / federated audit aggregators / SOX-compliance archival*). *(Commercial)* — extension point only; v1's `connection_factory: ConnectionFactory` injection point IS the plug-in seam where commercial overlays attach. Deferred to AD-456d-5.
- **Schema-version migration table.** v1 explicitly does not introduce a schema-version table — the assumption is the `AuditEntry` dataclass is stable (which it has been since AD-456 v1, Wave 7). If AD-456d-3 (tamper-response policy) ever adds a `tamper_state: str` field to `AuditEntry`, that AD must also handle the SQL migration. Not v1 territory.
- **No new pool, agent, or module beyond the 1 new EventType + 2 new config fields + the additive edits in `audit.py` + 1 new test file.**
- **No journal table or cross-store correlation surface.** Audit entries stay in `audit_log.db`; cross-correlation with cognitive journal, knowledge edges, or trust events is HXI / future-AD territory.
- **No coupling to `EarnedAgency` / `CredentialStore` / `EgressPolicy` / `RuntimeSandbox`.** AD-456d sits adjacent to the rest of the AD-456 cluster but is fully independent. It does not consult tier (AD-456c), egress policy (AD-456b), sandbox capability (AD-456b), or credential resolution (AD-395 / AD-456). The persistence layer is a pure storage seam over the existing in-memory hash chain.
- **No change to `AuditEntry` dataclass.** Frozen, 6 fields — the SQL schema mirrors these 6 fields exactly. Adding a `persisted: bool` field would break `verify_chain()` (`_hash` payload would include the new field, invalidating every existing entry's hash).
- **No change to `AuditLog.verify_chain()` / `AuditLog._hash()`.** Persistence is orthogonal to chain integrity.
- **No change to existing `AUDIT_RECORDED` emit semantics.** Existing 4 tests assert the emit fires synchronously from `append()` with payload `{sequence, category, entry_hash}`. New persist-task path is additive after the existing emit.
- **No `aiosqlite` import in `audit.py`.** All DB access goes through the injected `connection_factory: ConnectionFactory`. Tests use `SQLiteConnectionFactory()` from `probos.storage.sqlite_factory`. This preserves the cloud-ready abstraction (AD-466) and matches every other AD-622 / AD-524 / AD-687 SQLite-backed module.

---

## Verified Against Codebase (HEAD post-Wave-56, `7516bd8`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `AuditEntry` frozen dataclass (6 fields, mirror target for SQL schema) | `src/probos/security/audit.py` | 22-31 | `class AuditEntry:` … `entry_hash: str` |
| `AuditLog` dataclass (insertion target for `_persistence`/`_pending_writes`/`attach_persistence`) | `src/probos/security/audit.py` | 35-44 | `class AuditLog:` … `entries: list[AuditEntry] = field(default_factory=list)` … `emit_event: Any \| None = None` … `GENESIS_HASH: str = "0" * 64` |
| `AuditLog.append` (insertion target for fire-and-forget persist hook) | `src/probos/security/audit.py` | 48-85 | `def append(self, *, category: str, detail: str) -> AuditEntry:` … `return entry` |
| `AuditLog.append` AUDIT_RECORDED emit block (anchor — new persist-hook block goes immediately after, before `return entry`) | `src/probos/security/audit.py` | 70-83 | `if self.emit_event is not None:` … `entry_hash, category, exc_info=True,` |
| `AuditLog.verify_chain` (NOT modified) | `src/probos/security/audit.py` | 86 | `def verify_chain(self) -> bool:` |
| `AuditLog._hash` (NOT modified — anchor for AuditLogPersistence module-level append after) | `src/probos/security/audit.py` | 103 | `def _hash(self, payload: dict[str, Any]) -> str:` |
| `from __future__ import annotations` (already present — enables forward refs) | `src/probos/security/audit.py` | 8 | `from __future__ import annotations` |
| `from probos.events import EventType` (existing import — extended for AUDIT_PERSISTED) | `src/probos/security/audit.py` | 17 | `from probos.events import EventType` |
| `EventType.AUDIT_RECORDED` (existing AD-456 enum) | `src/probos/events.py` | 210 | `AUDIT_RECORDED = "audit_recorded"  # AD-456` |
| `EventType.SANDBOX_CAPABILITY_DENIED` / `CREDENTIAL_TIER_DENIED` (insertion-anchor siblings — line above) | `src/probos/events.py` | 212-213 | `SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b` … `CREDENTIAL_TIER_DENIED = "credential_tier_denied"  # AD-456c` |
| `EventType.VERIFICATION_PASSED` (insertion-anchor sibling — line below) | `src/probos/events.py` | 214 | `VERIFICATION_PASSED = "verification_passed"  # AD-528` |
| `SecurityInfraConfig` Pydantic class | `src/probos/config.py` | 1450 | `class SecurityInfraConfig(BaseModel):` |
| `SecurityInfraConfig.credential_tier_enforcement` (sibling — append point for new `audit_persistence_*` fields) | `src/probos/config.py` | 1478 | `credential_tier_enforcement: bool = False` |
| `SecurityInfraConfig.audit_enabled` (existing v1 flag — controls AuditLog construction) | `src/probos/config.py` | 1461 | `audit_enabled: bool = True` |
| `SecurityInfraConfig.secrets_store_filename` (sibling shape for new `audit_persistence_filename`) | `src/probos/config.py` | 1457 | `secrets_store_filename: str = "secrets.json"` |
| AD-456 finalize AuditLog block (insertion target — new wiring goes immediately after) | `src/probos/startup/finalize.py` | 1293-1297 | `if config.security_infra.audit_enabled:` … `runtime.audit_log = AuditLog(emit_event=runtime.emit_event)` … `runtime.audit_log = None` |
| `finalize_startup` is async (allows `await persistence.start()`) | `src/probos/startup/finalize.py` | 848 | `async def finalize_startup(` |
| AD-456b RuntimeSandbox block (sibling — new wiring goes BEFORE this block) | `src/probos/startup/finalize.py` | 1300 | `if config.security_infra.sandbox_enabled:` |
| `protocols.ConnectionFactory` Protocol (cloud-ready abstraction) | `src/probos/protocols.py` | 223 | `class ConnectionFactory(Protocol):` |
| `protocols.ConnectionFactory.connect` signature | `src/probos/protocols.py` | 232 | `async def connect(self, db_path: str) -> DatabaseConnection:` |
| `SQLiteConnectionFactory` + `default_factory` singleton | `src/probos/storage/sqlite_factory.py` | 10, 28 | `class SQLiteConnectionFactory:` … `default_factory = SQLiteConnectionFactory()` |
| `ClearanceGrantStore.start` PRAGMA shape (AD-622 mirror target — WAL/busy_timeout/synchronous) | `src/probos/clearance_grants.py` | 64-72 | `await self._db.execute("PRAGMA journal_mode=WAL")` … `await self._db.execute("PRAGMA busy_timeout=5000")` … `await self._db.execute("PRAGMA synchronous=NORMAL")` … `await self._db.executescript(_SCHEMA)` … `await self._db.commit()` |
| `ArchiveStore.__init__` (sibling shape — required-kwarg `connection_factory`) | `src/probos/knowledge/archive_store.py` | 63 | `def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:` |
| Existing AD-456 test file (no modification) | `tests/test_ad456_security_infrastructure.py` | 176-228 | 4 `TestAuditLog` tests pass at HEAD |
| Existing AD-456b test file (no modification) | `tests/test_ad456b_runtime_sandboxing.py` | — | passes at HEAD |
| Existing AD-456c test file (no modification) | `tests/test_ad456c_per_tier_credentials.py` | — | passes at HEAD |

`AuditLog._persistence`, `AuditLog._pending_writes`, `AuditLog.attach_persistence`, `AuditLogPersistence`, `AuditLogPersistence.start`/`stop`/`persist_entry`/`load_entries`/`count`, `_SCHEMA` constant, `EventType.AUDIT_PERSISTED`, `SecurityInfraConfig.audit_persistence_enabled`, `SecurityInfraConfig.audit_persistence_filename`, `runtime.audit_log_persistence`, `tests/test_ad456d_audit_log_persistence.py` — all greenfield, verified zero hits at HEAD `7516bd8`.

---

## Implementation

### Section 0 — Event Type

**File:** `src/probos/events.py`

`SEARCH` block (the AD-456b/AD-456c security-infra events plus their immediate context, lines 210-214):
```python
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
    CREDENTIAL_TIER_DENIED = "credential_tier_denied"  # AD-456c
    VERIFICATION_PASSED = "verification_passed"  # AD-528
```

`REPLACE`:
```python
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
    CREDENTIAL_TIER_DENIED = "credential_tier_denied"  # AD-456c
    AUDIT_PERSISTED = "audit_persisted"  # AD-456d
    VERIFICATION_PASSED = "verification_passed"  # AD-528
```

---

### Section 1 — `SecurityInfraConfig` extension

**File:** `src/probos/config.py`

`SEARCH` block (the AD-456c transitional flag + its multi-line comment, lines 1472-1478):
```python
    # AD-456c: Per-tier credential lookup gate (v1 default False — preserves
    # AD-456 ungated-lookup behavior on existing deployments; flip to True at
    # upgrade time after reviewing per-spec ``min_tier`` coverage. AD-456c-5
    # will flip default to True once fleet-wide ``min_tier`` coverage is
    # verified AND caller-side ``tier=`` argument propagation (AD-456c-2)
    # has landed in all production credential-using agent paths.).
    credential_tier_enforcement: bool = False
```

`REPLACE`:
```python
    # AD-456c: Per-tier credential lookup gate (v1 default False — preserves
    # AD-456 ungated-lookup behavior on existing deployments; flip to True at
    # upgrade time after reviewing per-spec ``min_tier`` coverage. AD-456c-5
    # will flip default to True once fleet-wide ``min_tier`` coverage is
    # verified AND caller-side ``tier=`` argument propagation (AD-456c-2)
    # has landed in all production credential-using agent paths.).
    credential_tier_enforcement: bool = False

    # AD-456d: AuditLog SQLite persistence (v1 default False — preserves
    # AD-456 in-memory-only audit chain on existing deployments; flip to
    # True at upgrade time after rehearsing rehydrate-on-boot against a
    # production-shaped audit trail. AD-456d-4 will flip default to True
    # once AD-456d-1 (shutdown-flush hook) lands.).
    audit_persistence_enabled: bool = False
    audit_persistence_filename: str = "audit_log.db"
```

---

### Section 2 — `AuditLog` extensions + `AuditLogPersistence`

**File:** `src/probos/security/audit.py`

#### Section 2a — `AuditLog` adds `_persistence` + `_pending_writes` fields

`SEARCH` block (the existing `AuditLog` dataclass body + the `GENESIS_HASH` class variable + the start of `append`, lines 33-48):
```python
@dataclass
class AuditLog:
    """In-memory hash-chained log.

    Append-only. Each entry's hash includes the prior entry's hash so any
    tampering breaks the chain. ``verify_chain()`` re-derives every hash and
    confirms continuity.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None

    GENESIS_HASH: str = "0" * 64

    def append(self, *, category: str, detail: str) -> AuditEntry:
```

`REPLACE`:
```python
@dataclass
class AuditLog:
    """In-memory hash-chained log.

    Append-only. Each entry's hash includes the prior entry's hash so any
    tampering breaks the chain. ``verify_chain()`` re-derives every hash and
    confirms continuity.

    AD-456d: Optional ``_persistence`` field accepts an ``AuditLogPersistence``
    instance via ``attach_persistence(...)``. When attached AND a running
    asyncio loop is present at ``append()`` time, each new entry is also
    scheduled for SQLite persistence as a fire-and-forget task tracked in
    ``_pending_writes``. Sync ``append()`` return path is unchanged — the
    in-memory chain remains the source of truth at runtime.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None
    # AD-456d: optional persistence seam. Defaults None preserve AD-456
    # in-memory-only contract. Set via ``attach_persistence(...)``.
    _persistence: "AuditLogPersistence | None" = None
    # AD-456d: in-flight persist task references (copilot-instructions Async
    # Discipline rule — fire-and-forget tasks must hold a reference or they
    # may be garbage-collected before completion). Each task adds itself
    # via ``set.add(task)`` and registers ``task.add_done_callback(set.discard)``.
    _pending_writes: set["asyncio.Task[Any]"] = field(default_factory=set)

    GENESIS_HASH: str = "0" * 64

    def append(self, *, category: str, detail: str) -> AuditEntry:
```

#### Section 2b — `AuditLog.attach_persistence` setter

`SEARCH` block (the `AuditLog.verify_chain` body close + the `_hash` head, lines 99-103):
```python
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def _hash(self, payload: dict[str, Any]) -> str:
```

`REPLACE`:
```python
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def attach_persistence(self, persistence: "AuditLogPersistence") -> None:
        """AD-456d: Attach an ``AuditLogPersistence`` instance.

        Pure setter — no other side effects. After attachment, each
        subsequent ``append()`` schedules a fire-and-forget SQLite write
        when a running asyncio loop is present. Mirrors
        ``OracleService.attach_semantic_layer`` shape from AD-686b.
        """
        self._persistence = persistence

    def _hash(self, payload: dict[str, Any]) -> str:
```

#### Section 2c — `AuditLog.append` fire-and-forget persist hook

`SEARCH` block (the existing `append` body — full body including AUDIT_RECORDED emit + `return entry`, lines 48-84):
```python
    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = self.entries[-1].entry_hash if self.entries else self.GENESIS_HASH
        sequence = len(self.entries)
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        return entry
```

`REPLACE`:
```python
    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = self.entries[-1].entry_hash if self.entries else self.GENESIS_HASH
        sequence = len(self.entries)
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        # AD-456d: fire-and-forget persist hook. No-op when persistence is
        # not attached OR no asyncio loop is running (sync test paths).
        if self._persistence is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug(
                    "AD-456d: AuditLog.append called without running loop "
                    "(sequence=%d); persistence skipped",
                    sequence,
                )
            else:
                task = loop.create_task(self._persistence.persist_entry(entry))
                self._pending_writes.add(task)
                task.add_done_callback(self._pending_writes.discard)
        return entry
```

ALSO add `import asyncio` to the existing imports at the top of the module.

`SEARCH` block (the existing imports, lines 8-17):
```python
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType
```

`REPLACE`:
```python
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection
```

(`TYPE_CHECKING` guard for the `ConnectionFactory` / `DatabaseConnection` annotations on `AuditLogPersistence` — avoids a runtime import when the persistence class isn't constructed.)

#### Section 2d — `AuditLogPersistence` class + `_SCHEMA` constant

`SEARCH` block (the end of the existing `AuditLog._hash` method body — the file's current trailing content, lines 103-105):
```python
    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
```

`REPLACE`:
```python
    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# AD-456d: SQLite persistence layer
# ---------------------------------------------------------------------------

# Schema mirrors ``AuditEntry`` 1-for-1. ``sequence`` is the natural primary
# key (already monotonic per ``len(self.entries)``-based assignment in
# ``AuditLog.append``); ``entry_hash`` is unique per the SHA-256-of-prior-hash
# chain semantics. Index on ``timestamp`` supports AD-456d-7 future range
# queries from the HXI inspection surface.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    sequence INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    category TEXT NOT NULL,
    detail TEXT NOT NULL,
    prior_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""


class AuditLogPersistence:
    """AD-456d: SQLite-backed persistence for ``AuditLog``.

    Cloud-ready via injected ``connection_factory: ConnectionFactory``
    (AD-466). Mirrors ``ClearanceGrantStore`` (AD-622) WAL/busy_timeout/
    synchronous PRAGMA shape exactly. Writes are append-only; reads are
    used at boot to rehydrate the in-memory chain.

    v1 ships start + persist_entry + load_entries + count + stop. The
    ``stop()`` method is defined but NOT wired into runtime shutdown in
    v1 (deferred to AD-456d-1 — paired with similar shutdowns for
    ``ClearanceGrantStore``, ``CognitiveJournal``, etc.). Tests call
    ``stop()`` directly.
    """

    def __init__(
        self,
        *,
        db_path: str,
        connection_factory: "ConnectionFactory",
        emit_event: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._emit_event = emit_event
        self._db: Any = None

    async def start(self) -> None:
        """Open the connection, set PRAGMAs, create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-456d: AuditLogPersistence started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the connection. NOT wired into runtime shutdown in v1
        (deferred to AD-456d-1). Tests call directly.
        """
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_entry(self, entry: AuditEntry) -> None:
        """Insert one ``AuditEntry`` row + commit + emit ``AUDIT_PERSISTED``.

        Tier-2 log-and-degrade — SQLite write failures NEVER propagate up to
        the sync ``append()`` caller (which scheduled this as a fire-and-
        forget task). The deny decision is already chained in memory and
        emitted as ``AUDIT_RECORDED``; the persist channel is observer-only.
        """
        if self._db is None:
            logger.warning(
                "AD-456d: persist_entry called before start() (sequence=%d)",
                entry.sequence,
            )
            return
        try:
            await self._db.execute(
                """INSERT INTO audit_log
                       (sequence, timestamp, category, detail, prior_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.sequence,
                    entry.timestamp,
                    entry.category,
                    entry.detail,
                    entry.prior_hash,
                    entry.entry_hash,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-456d: AuditLog persist failed (sequence=%d, category=%s)",
                entry.sequence, entry.category, exc_info=True,
            )
            return
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.AUDIT_PERSISTED,
                    {
                        "sequence": entry.sequence,
                        "entry_hash": entry.entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456d: AUDIT_PERSISTED emit failed (sequence=%d)",
                    entry.sequence, exc_info=True,
                )

    async def load_entries(self) -> list[AuditEntry]:
        """Return all rows ordered by sequence ASC for chain rehydration.

        ORDER BY sequence is REQUIRED — without it, SQLite is permitted to
        return rows in any order, which would shuffle the prior_hash chain
        and break ``verify_chain()`` after rehydrate.
        """
        if self._db is None:
            return []
        cursor = await self._db.execute(
            """SELECT sequence, timestamp, category, detail, prior_hash, entry_hash
               FROM audit_log ORDER BY sequence ASC"""
        )
        rows = await cursor.fetchall()
        return [
            AuditEntry(
                sequence=row[0],
                timestamp=row[1],
                category=row[2],
                detail=row[3],
                prior_hash=row[4],
                entry_hash=row[5],
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total persisted rows (testability helper)."""
        if self._db is None:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM audit_log")
        row = await cursor.fetchone()
        return row[0] if row else 0
```

---

### Section 3 — `startup/finalize.py` wiring

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (the existing AD-456 AuditLog wiring + the surrounding context, lines 1293-1300):
```python
    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None

    # AD-456b: Runtime Sandboxing
```

`REPLACE`:
```python
    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None

    # AD-456d: AuditLog SQLite persistence. Whole block is try/except —
    # boot continues with runtime.audit_log_persistence=None on any
    # failure (mirrors AD-456 CredentialStore extension shape).
    runtime.audit_log_persistence = None
    if (
        runtime.audit_log is not None
        and config.security_infra.audit_persistence_enabled
    ):
        try:
            from probos.security.audit import AuditLogPersistence
            from probos.storage.sqlite_factory import SQLiteConnectionFactory
            persistence = AuditLogPersistence(
                db_path=str(
                    runtime.data_dir / config.security_infra.audit_persistence_filename
                ),
                connection_factory=SQLiteConnectionFactory(),
                emit_event=runtime.emit_event,
            )
            await persistence.start()
            loaded = await persistence.load_entries()
            if loaded:
                runtime.audit_log.entries.extend(loaded)
                if not runtime.audit_log.verify_chain():
                    logger.warning(
                        "AD-456d: AuditLog chain verification FAILED on "
                        "rehydrate (tamper or corruption suspected; "
                        "AD-456d-3 will add Captain alert path)"
                    )
            runtime.audit_log.attach_persistence(persistence)
            runtime.audit_log_persistence = persistence
            logger.info(
                "AD-456d: AuditLog persistence wired (db=%s, rehydrated=%d)",
                persistence._db_path, len(loaded),
            )
        except Exception:
            logger.warning(
                "AD-456d: AuditLog persistence wiring failed (boot continues "
                "with in-memory-only audit chain)",
                exc_info=True,
            )
            runtime.audit_log_persistence = None

    # AD-456b: Runtime Sandboxing
```

---

### Section 4 — Tests

**File:** `tests/test_ad456d_audit_log_persistence.py` (NEW)

14 tests:

```python
"""AD-456d: AuditLog SQLite persistence tests."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.events import EventType
from probos.security.audit import (
    AuditEntry,
    AuditLog,
    AuditLogPersistence,
    _SCHEMA,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_log(*, with_emit: bool = False) -> tuple[AuditLog, MagicMock | None]:
    emit = MagicMock() if with_emit else None
    log = AuditLog(emit_event=emit)
    return log, emit


def _make_persistence(
    tmp_path: Path,
    *,
    filename: str = "audit_test.db",
    with_emit: bool = False,
) -> tuple[AuditLogPersistence, MagicMock | None]:
    emit = MagicMock() if with_emit else None
    persistence = AuditLogPersistence(
        db_path=str(tmp_path / filename),
        connection_factory=SQLiteConnectionFactory(),
        emit_event=emit,
    )
    return persistence, emit


# ---------------------------------------------------------------------------
# Backwards compat — AuditLog without persistence
# ---------------------------------------------------------------------------

def test_auditlog_constructs_without_persistence_unchanged() -> None:
    """AD-456 v1 contract preserved: AuditLog with no persistence behaves
    identically to today (sync append, in-memory chain, AUDIT_RECORDED emit).
    """
    log, emit = _make_log(with_emit=True)
    assert log._persistence is None
    assert log._pending_writes == set()

    e = log.append(category="auth", detail="login user=alice")

    assert isinstance(e, AuditEntry)
    assert e.sequence == 0
    assert log.entries == [e]
    assert emit is not None
    emit.assert_called_once()
    args = emit.call_args.args
    assert args[0] == EventType.AUDIT_RECORDED


def test_attach_persistence_sets_field_no_other_side_effects() -> None:
    """attach_persistence is a pure setter (mirrors OracleService.attach_semantic_layer)."""
    log, _ = _make_log(with_emit=False)
    fake_persistence = MagicMock(spec=AuditLogPersistence)

    log.attach_persistence(fake_persistence)

    assert log._persistence is fake_persistence
    # No other side effects — entries unchanged, pending_writes still empty.
    assert log.entries == []
    assert log._pending_writes == set()


# ---------------------------------------------------------------------------
# AuditLogPersistence — start / stop / count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistence_start_creates_schema_and_starts_empty(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        assert await persistence.count() == 0
        # Schema constant is non-empty and references the table name.
        assert "audit_log" in _SCHEMA
        assert "entry_hash" in _SCHEMA
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# persist_entry — single + multiple + ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_entry_inserts_one_row(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=bob",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="a" * 64,
        )
        await persistence.persist_entry(entry)
        assert await persistence.count() == 1

        loaded = await persistence.load_entries()
        assert len(loaded) == 1
        assert loaded[0] == entry
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_persist_entry_multiple_preserves_sequence(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        for i in range(3):
            await persistence.persist_entry(
                AuditEntry(
                    sequence=i,
                    timestamp=1700000000.0 + i,
                    category="evt",
                    detail=f"item-{i}",
                    prior_hash=("0" * 64) if i == 0 else (str(i - 1) * 64),
                    entry_hash=str(i) * 64,
                )
            )
        assert await persistence.count() == 3
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_load_entries_returns_rows_in_sequence_order(tmp_path: Path) -> None:
    """Locks the SQL ``ORDER BY sequence ASC`` requirement — without it,
    SQLite may return rows in any order, breaking chain rehydration.
    """
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        # Insert deliberately out of order to verify ORDER BY does the work.
        for i in [4, 0, 2, 3, 1]:
            await persistence.persist_entry(
                AuditEntry(
                    sequence=i,
                    timestamp=1700000000.0 + i,
                    category="evt",
                    detail=f"item-{i}",
                    prior_hash=("0" * 64),
                    entry_hash=f"{i:064d}",
                )
            )

        loaded = await persistence.load_entries()
        assert [e.sequence for e in loaded] == [0, 1, 2, 3, 4]
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# Append + persistence integration — fire-and-forget task path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_with_persistence_attached_persists_via_task(tmp_path: Path) -> None:
    """AuditLog.append schedules a fire-and-forget persist task when a
    running loop is present; awaiting _pending_writes synchronises.
    """
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        log, _ = _make_log(with_emit=False)
        log.attach_persistence(persistence)

        log.append(category="auth", detail="login user=carol")
        # Must have scheduled exactly one task.
        assert len(log._pending_writes) == 1

        # Synchronise — gather drains the set as tasks complete (via
        # add_done_callback). Snapshot first so iteration is stable.
        pending = list(log._pending_writes)
        await asyncio.gather(*pending)

        assert await persistence.count() == 1
        # done_callback drained the set.
        assert log._pending_writes == set()
    finally:
        await persistence.stop()


def test_append_without_running_loop_is_silent_noop_with_debug_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Sync append() with persistence attached but no running loop logs
    DEBUG and returns the entry — must not raise.
    """
    log, _ = _make_log(with_emit=False)
    fake_persistence = MagicMock(spec=AuditLogPersistence)
    log.attach_persistence(fake_persistence)

    caplog.set_level(logging.DEBUG, logger="probos.security.audit")
    e = log.append(category="auth", detail="login user=dave")

    assert isinstance(e, AuditEntry)
    assert log._pending_writes == set()
    fake_persistence.persist_entry.assert_not_called()
    assert any(
        "without running loop" in rec.message
        for rec in caplog.records
    )


def test_append_without_persistence_is_unchanged_sync_noop() -> None:
    """No persistence attached → no task scheduling, no warning, _pending_writes empty."""
    log, _ = _make_log(with_emit=False)
    e = log.append(category="auth", detail="login user=eve")
    assert isinstance(e, AuditEntry)
    assert log._pending_writes == set()
    assert log._persistence is None


# ---------------------------------------------------------------------------
# AUDIT_PERSISTED event + persist failure handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_persisted_event_emitted_after_successful_insert(
    tmp_path: Path,
) -> None:
    persistence, emit = _make_persistence(tmp_path, with_emit=True)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=fred",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="b" * 64,
        )
        await persistence.persist_entry(entry)

        assert emit is not None
        persisted_calls = [
            c for c in emit.call_args_list
            if c.args and c.args[0] == EventType.AUDIT_PERSISTED
        ]
        assert len(persisted_calls) == 1
        payload = persisted_calls[0].args[1]
        assert payload == {"sequence": 0, "entry_hash": "b" * 64}
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_persist_entry_failure_logs_and_does_not_propagate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Tier-2 log-and-degrade: SQLite errors must not escape persist_entry."""
    persistence, emit = _make_persistence(tmp_path, with_emit=True)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=ginger",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="c" * 64,
        )
        await persistence.persist_entry(entry)
        assert await persistence.count() == 1

        # Insert again with the same sequence (PK collision) — must NOT raise.
        caplog.set_level(logging.WARNING, logger="probos.security.audit")
        await persistence.persist_entry(entry)
        # Count unchanged — second insert failed silently.
        assert await persistence.count() == 1
        assert any(
            "AuditLog persist failed" in rec.message
            for rec in caplog.records
        )
        # AUDIT_PERSISTED emitted once for the successful insert; NOT twice.
        assert emit is not None
        persisted_count = sum(
            1 for c in emit.call_args_list
            if c.args and c.args[0] == EventType.AUDIT_PERSISTED
        )
        assert persisted_count == 1
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# Rehydrate on boot — verify_chain happy + tamper detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rehydrate_extend_then_verify_chain_intact(tmp_path: Path) -> None:
    """First-run: append 3 entries to AuditLog → persist via task path.
    Second-run: fresh AuditLog + load_entries → extend → verify_chain True.
    """
    db_file = tmp_path / "audit_rehydrate.db"

    # First-run cycle.
    persistence_1 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_1.start()
    log_1, _ = _make_log(with_emit=False)
    log_1.attach_persistence(persistence_1)
    for i in range(3):
        log_1.append(category="evt", detail=f"item-{i}")
    await asyncio.gather(*list(log_1._pending_writes))
    assert await persistence_1.count() == 3
    await persistence_1.stop()

    # Second-run cycle: rehydrate.
    persistence_2 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_2.start()
    try:
        loaded = await persistence_2.load_entries()
        assert len(loaded) == 3

        log_2, _ = _make_log(with_emit=False)
        log_2.entries.extend(loaded)
        assert log_2.verify_chain() is True
    finally:
        await persistence_2.stop()


@pytest.mark.asyncio
async def test_rehydrate_after_db_tamper_verify_chain_false(tmp_path: Path) -> None:
    """If a row is mutated in the DB out-of-band, rehydrate + verify_chain
    catches it (returns False). Locks the warn-don't-fail-boot contract:
    finalize wiring logs WARNING and continues.
    """
    db_file = tmp_path / "audit_tamper.db"

    persistence_1 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_1.start()
    log_1, _ = _make_log(with_emit=False)
    log_1.attach_persistence(persistence_1)
    for i in range(3):
        log_1.append(category="evt", detail=f"item-{i}")
    await asyncio.gather(*list(log_1._pending_writes))
    # Tamper the middle row's detail without recomputing hash.
    await persistence_1._db.execute(
        "UPDATE audit_log SET detail = ? WHERE sequence = 1",
        ("MUTATED",),
    )
    await persistence_1._db.commit()
    await persistence_1.stop()

    # Second-run: rehydrate + verify.
    persistence_2 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_2.start()
    try:
        loaded = await persistence_2.load_entries()
        log_2, _ = _make_log(with_emit=False)
        log_2.entries.extend(loaded)
        # Tamper detected.
        assert log_2.verify_chain() is False
    finally:
        await persistence_2.stop()


# ---------------------------------------------------------------------------
# Custom ConnectionFactory injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistence_accepts_custom_connection_factory(tmp_path: Path) -> None:
    """connection_factory is a required kwarg; tests can inject a custom
    factory that wraps SQLiteConnectionFactory (or anything implementing
    the ConnectionFactory Protocol). Locks the cloud-ready seam.
    """
    calls: list[str] = []

    class WrappingFactory:
        def __init__(self) -> None:
            self._inner = SQLiteConnectionFactory()

        async def connect(self, db_path: str) -> Any:
            calls.append(db_path)
            return await self._inner.connect(db_path)

    factory = WrappingFactory()
    db_file = tmp_path / "audit_custom_factory.db"
    persistence = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=factory,
    )
    await persistence.start()
    try:
        assert calls == [str(db_file)]
        assert await persistence.count() == 0
    finally:
        await persistence.stop()
```

---

## Tracking

- `PROGRESS.md` — prepend AD-456d CLOSED entry (Era V). (Note: AD-456c builder skipped this step in Wave 56; if precedent holds, the Captain may handle the tracker update separately. Builder should ATTEMPT the prepend; non-blocker if skipped.)
- `docs/development/roadmap.md` — flip the AD-456d row to ✅ shipped under the AD-456 cluster; add deferral entries:
  - **AD-456d-1**: Shutdown-flush hook (`runtime.audit_log_persistence.stop()` wired into runtime shutdown sequence — pair with similar shutdowns).
  - **AD-456d-2**: Batched persist queue + drain loop (perf optimisation vs per-append `create_task`).
  - **AD-456d-3**: Tamper-on-rehydrate Captain-alert path (`EventType.AUDIT_TAMPER_DETECTED` + alert routing; today: log-WARNING only).
  - **AD-456d-4**: Default-flip of `audit_persistence_enabled` to True once AD-456d-1 lands.
  - **AD-456d-5** *(Commercial)*: Postgres / cloud audit-storage adapters / federated audit aggregators / SOX-compliance archival — extension point on the existing `protocols.ConnectionFactory` (already shipped AD-466).
  - **AD-456d-6**: Retention policy (TTL or row cap) + archival to ShipsArchive.
  - **AD-456d-7**: HXI inspection surface (`/audit list`, `/audit verify`, `/audit since <ts>` shell commands).
- `DECISIONS.md` — prepend AD-456d entry at the top of Era V. (Same precedent caveat as PROGRESS.md.)

---

## Acceptance Criteria

- All 14 new tests in `tests/test_ad456d_audit_log_persistence.py` pass.
- All existing tests in `tests/test_ad456_security_infrastructure.py::TestAuditLog` (4 tests, lines 176-228) pass UNCHANGED.
- All 12 existing AD-456b tests in `tests/test_ad456b_runtime_sandboxing.py` pass UNCHANGED.
- All 13 existing AD-456c tests in `tests/test_ad456c_per_tier_credentials.py` pass UNCHANGED.
- All existing tests in `tests/test_credential_store.py` pass UNCHANGED.
- Full gate (`pytest tests/ -q -n 8 --dist=loadfile`) net-passes at **11266** (baseline 11252 + 14 new), ceiling **11267** (one fixture-split discovery permitted per Wave-30/39/41/42/53/55/56 precedent).
- No existing-symbol modification beyond the additive members (new fields default; new method is opt-in; `append()` signature + sync return + AUDIT_RECORDED emit unchanged).
- `AuditEntry`, `AuditLog.verify_chain`, `AuditLog._hash` UNCHANGED.
- `runtime.audit_log` instance is the same object created by the existing AD-456 wiring; AD-456d wiring extends it via `attach_persistence`, never re-instantiates.
- `audit.py` does NOT import `aiosqlite` directly — all DB access via the injected `ConnectionFactory`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
