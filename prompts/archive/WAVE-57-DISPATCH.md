# WAVE 57 DISPATCH — AD-456d v1 Security Infrastructure: AuditLog SQLite Persistence

**Wave id:** 57
**Single AD:** AD-456d
**Closes:** #400
**Baseline test count:** 11252 (Wave 56, commit `7516bd8`) → expected **11266** (+14 net), ceiling **+15**
**HEAD at draft:** post-Wave-56 (`7516bd8`, working tree clean)

## Summary

AD-456 v1 (Wave 7) shipped `AuditLog` (`src/probos/security/audit.py`) — an append-only, SHA-256 hash-chained, in-memory record with `verify_chain()` tamper detection. The module's own docstring contracts the gap (`audit.py:1-6`):

> "v1 in-memory only. … Persistence to SQLite deferred to AD-456d."

The roadmap entry (`docs/development/roadmap.md:4148`) names AD-456d:

> "Persist inference audit log entries to SQLite for post-incident forensic review. v1 audit layer logs to Python logger only — entries lost on restart. Must use cloud-ready storage abstraction. Same persistence pattern as AD-635b."

(The roadmap "logs to Python logger only" line is imprecise — actual v1 keeps a SHA-256-chained `list[AuditEntry]` in memory plus emits `AUDIT_RECORDED`. The entries-lost-on-restart consequence is correct; the root cause is in-memory storage, not logger-only output.)

AD-456d v1 ships:

1. **`AuditLogPersistence`** — new class in `audit.py`. Cloud-ready via `protocols.ConnectionFactory` (AD-466 abstraction). API: `__init__(*, db_path, connection_factory)`, `async start()`, `async stop()`, `async persist_entry(entry)`, `async load_entries()`, `async count()`. Mirrors `ClearanceGrantStore` (AD-622) WAL/busy_timeout/synchronous PRAGMA shape exactly.

2. **`AuditLog._persistence: "AuditLogPersistence | None" = None`** + **`AuditLog._pending_writes: set[asyncio.Task[Any]] = field(default_factory=set)`** — additive dataclass fields. Default values preserve the AD-456 sync contract bit-for-bit; existing 4 tests in `test_ad456_security_infrastructure.py::TestAuditLog` continue to pass without modification.

3. **`AuditLog.attach_persistence(persistence)`** — public setter. Mirrors `OracleService.attach_semantic_layer` shape from AD-686b (Wave 50).

4. **`AuditLog.append()` extended with fire-and-forget persist**. After in-memory append + `AUDIT_RECORDED` emit (both unchanged), if `_persistence is not None` AND a running loop is present (`try asyncio.get_running_loop(); except RuntimeError: skip with debug log`), schedule `loop.create_task(self._persistence.persist_entry(entry))`. Task held in `self._pending_writes` set with `add_done_callback(self._pending_writes.discard)` — no fire-and-forget garbage-collection bug (copilot-instructions Async Discipline rule).

5. **`EventType.AUDIT_PERSISTED`** — single new enum value. Inserted adjacent to `AUDIT_RECORDED`/`SANDBOX_*`/`CREDENTIAL_TIER_DENIED` cluster, immediately after `CREDENTIAL_TIER_DENIED` (line 213). Emitted by `persist_entry` on successful row insert; never emitted on failure (log-and-degrade path).

6. **`SecurityInfraConfig.audit_persistence_enabled: bool = False`** + **`SecurityInfraConfig.audit_persistence_filename: str = "audit_log.db"`** — two new Pydantic fields appended after `credential_tier_enforcement`. Convention #14 + #3 + Wave 55 / Wave 56 sibling pattern: default False on the transitional flag; AD-456d-4 flips default to True once shutdown-flush wiring (AD-456d-1) lands.

7. **`startup/finalize.py` wiring** — single new if-block inserted IMMEDIATELY AFTER the existing `audit_log = AuditLog(...)` block (lines 1293-1297) and BEFORE the AD-456b `RuntimeSandbox` block. Path: `runtime.data_dir / config.security_infra.audit_persistence_filename`. Constructs `AuditLogPersistence` with `SQLiteConnectionFactory()`, `await persistence.start()`, rehydrates `runtime.audit_log.entries` from `await persistence.load_entries()` IF non-empty, calls `runtime.audit_log.verify_chain()` and logs WARNING on tamper detection (does NOT block boot — observer signal; tamper-response policy deferred to AD-456d-3), then `runtime.audit_log.attach_persistence(persistence)`. Sets `runtime.audit_log_persistence = persistence` for AD-456d-1 shutdown-flush hook (greenfield runtime attribute — verified zero hits at HEAD `7516bd8`).

5 sections + Section 0 EventType, 4 source-edit files (`events.py`, `config.py`, `audit.py` — substantial additive content, `startup/finalize.py`), 1 new test file (14 tests).

The shutdown flush hook (`runtime.audit_log_persistence.stop()` at process exit), batched-write queue (single drain task vs per-append `create_task`), tamper-on-rehydrate Captain-alert path, default-flip of `audit_persistence_enabled`, retention/TTL policy, HXI inspection surface (`/audit list/verify`), and commercial overlays (Postgres/cloud audit-storage adapters via `ConnectionFactory` extension point — already shipped AD-466) are pre-deferred at the prompt level to AD-456d-1 / -2 / -3 / -4 / -6 / -7 / -5 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — Mirror AD-456b/AD-456c transitional-flag posture exactly.** Convention #14 + #3 + Waves 55/56 precedent: default-False on the new transitional flag. `egress_active_enforcement` (AD-456b) and `credential_tier_enforcement` (AD-456c) are the two immediate sibling patterns; `audit_persistence_enabled` follows the same naming, default, comment shape, and finalize-block conditional. Deviation from the established sibling pattern would burn review cycles for nothing — pre-applied. Forcing function: AD-456d-4 flips default to True once AD-456d-1 (shutdown flush) lands.

- **DLog #2 — Two config fields, not one.** `audit_persistence_filename: str = "audit_log.db"` mirrors `secrets_store_filename` (AD-456 v1, `config.py:1457`) — every persistent file under `runtime.data_dir` exposes its filename as a Pydantic-configurable string. Operators with multi-tenant deployments need filename-level control without overriding `data_dir`. Same shape, same precedent, two fields not one.

- **DLog #3 — `_pending_writes: set[asyncio.Task[Any]]` field-tracked.** Copilot-instructions Async Discipline rule: "Always hold a reference to tasks created with `asyncio.create_task()`. Fire-and-forget tasks silently swallow exceptions and can be garbage collected. Store in a set or instance variable and remove on completion." `set` (not `list`) for O(1) discard; `add_done_callback(self._pending_writes.discard)` is the canonical idiom. Test #7 asserts a row lands by gathering `await asyncio.gather(*log._pending_writes)` after `append()` — the deterministic synchronisation point.

- **DLog #4 — `loop.create_task(...)` not `asyncio.create_task(...)`.** Copilot-instructions: "Always use `asyncio.get_running_loop()`, never `get_event_loop()`." We need to first probe whether a loop is running (sync `append()` may be called from a sync test or sync-only code path); the canonical safe shape is `try: loop = asyncio.get_running_loop(); except RuntimeError: return` followed by `loop.create_task(...)`. Equivalent to module-level `asyncio.create_task` when a loop is running, but the explicit get-or-skip path is required because sync callers must NOT raise on missing loop. Test #8 locks the no-loop path returns silently with a debug log.

- **DLog #5 — Sync `append()` signature unchanged.** Existing 4 tests in `test_ad456_security_infrastructure.py::TestAuditLog` (lines 176-228 in the file head) call `log.append(category=..., detail=...)` synchronously and rely on the immediate `AuditEntry` return. Wave-10 reframe consideration: switching `append()` to async would break these 4 tests + force a callsite migration audit. v1 keeps `append()` sync; persistence runs as a fire-and-forget task. The kw-only signature is unchanged. Test #1 explicitly locks backwards compat.

- **DLog #6 — Rehydrate BEFORE attach_persistence.** If `attach_persistence()` runs before `load_entries() → entries.extend(...)`, then a misconfigured caller that calls `append()` between the two steps would schedule a write task BEFORE rehydrate completes — interleaving boot-time writes and existing-row reads. Section 3 finalize sequence is explicit: `start()` → `load_entries()` → `entries.extend(loaded)` → `verify_chain()` (warn-only) → `attach_persistence()`. Test #12 locks the rehydrate-then-attach order via a SimpleNamespace `runtime` stand-in.

- **DLog #7 — Tamper-on-rehydrate is log-WARNING, NOT boot-fail.** v1 ships the persistence layer; tamper-response policy is AD-456d-3 (Captain-alert path + EventType.AUDIT_TAMPER_DETECTED). v1 stance: a tampered DB on boot is a degraded but recoverable state — log loudly, continue boot, let the operator decide. Boot-failing on tamper would mean a single corrupted row makes the whole runtime unstartable; that's a worse failure mode than a noisy log + observer. Test #13 locks the warn-don't-fail behavior.

- **DLog #8 — `AUDIT_PERSISTED` event distinct from `AUDIT_RECORDED`.** Existing `AUDIT_RECORDED` fires synchronously from `append()` after the in-memory append (AD-456 contract). New `AUDIT_PERSISTED` fires asynchronously from `persist_entry` after the SQLite INSERT commits. Two events, two semantic levels: "the system observed and chained this audit fact" (RECORDED) vs "the system durably persisted this audit fact" (PERSISTED). HXI dashboards and downstream consumers can subscribe to either. Test #10 locks the new event payload shape (`sequence`, `entry_hash`).

- **DLog #9 — Per-append `create_task`, NOT a batched queue.** Wave-10 reframe pre-application: the obvious perf optimisation (single drain task that flushes a queue) introduces a state machine (queue depth, drain interval, backpressure semantics) that's substantial v1 risk for a feature whose only existing caller-base is `tests/test_ad456_security_infrastructure.py::TestAuditLog`. v1 ships the simple shape (one task per append); AD-456d-2 layers a queue+drain optimisation on top once a real production caller surfaces and a perf signal appears. The fire-and-forget task pattern is correct (DLog #3 task tracking) and survives the audit-load cardinality of every production call site we have today (zero).

- **DLog #10 — `persist_entry` is log-and-degrade tier (3-tier rule, tier 2).** SQLite write failures must NOT propagate up to the sync `append()` caller — the deny decision (audit fact) is already chained in memory and emitted as `AUDIT_RECORDED`; the persist channel is a third-party observer for which a failure is non-critical. Mirrors `_emit_rotated` (`credential_store.py:262-264`) and `_emit_tier_denied` (`credential_store.py` AD-456c) exactly. Test #11 locks the swallow-and-warn shape.

- **DLog #11 — `runtime.audit_log_persistence` is a NEW public attribute.** Convention #1 (Wave 5): public attribute, no underscore. Greenfield — verified zero hits at HEAD `7516bd8`. AD-456d-1 shutdown-flush hook (deferred) will read `runtime.audit_log_persistence` to call `await persistence.stop()` at process exit. v1 sets the attribute even though no shutdown sequence reads it yet — consumers can opt in (HXI / introspection / future shutdown wiring) without a follow-up structural change.

- **DLog #12 — `_persistence` is INSTANCE attribute (no underscore-public dance).** Mirrors `AuditLog._emit_event` (existing AD-456 shape, line 36 — also single-underscore). The setter `attach_persistence(persistence)` is the public API; reads from outside the class (e.g. tests inspecting `log._pending_writes`) are convenience-tier and follow the same convention as `log.entries` access in existing tests. Public-attribute promotion (mirror of AD-680 pattern for `runtime.emit_event`) is deferrable to AD-456d-N if a real consumer needs it.

- **DLog #13 — `AuditEntry` dataclass UNCHANGED.** Frozen, 6 fields (`sequence`, `timestamp`, `category`, `detail`, `prior_hash`, `entry_hash`). SQL schema mirrors these 6 columns 1-for-1 with `sequence INTEGER PRIMARY KEY` (already monotonic per `len(self.entries)`-based assignment) + `entry_hash TEXT NOT NULL UNIQUE` (already unique per SHA-256-of-prior-hash chain semantics). `dataclasses.asdict` for INSERT, manual reconstruction for SELECT (avoid `**row` → `AuditEntry(**row)` brittleness against future field reorder).

- **DLog #14 — `_AGENCY_ORDER`-style local constant or full `protocols.ConnectionFactory` import?** Full import. AD-456c took the local-copy posture for `_AGENCY_ORDER` because it duplicated 4 strings (`reactive`/`suggestive`/`autonomous`/`unrestricted`) — a trivial constant. AD-456d needs the full `ConnectionFactory` Protocol surface (`async def connect(db_path) -> DatabaseConnection`); duplicating the Protocol locally would violate DRY for no Demeter benefit. ClearanceGrantStore (AD-622, `clearance_grants.py:17`), ArchiveStore (AD-524, `knowledge/archive_store.py:19`), CognitiveJournal, KnowledgeEdgeStore, and the rest of the SQLite-backed stores all import `from probos.protocols import ConnectionFactory` directly. AD-456d follows the established sibling pattern.

- **DLog #15 — `connection_factory` is REQUIRED keyword arg, NOT defaulted to SQLiteConnectionFactory.** ArchiveStore (AD-524) ships this exact shape (`def __init__(self, db_path: str, *, connection_factory: ConnectionFactory)` — required). ClearanceGrantStore (AD-622) defaults to `default_factory` from `storage/sqlite_factory.py`. Both shapes are precedented; we choose REQUIRED because AD-456d ships a NEW class whose tests want to inject stub factories (test #14: custom-factory injection). Defaulting would hide the seam from tests. Finalize wiring at Section 3 supplies `SQLiteConnectionFactory()` explicitly — one line, zero ambiguity.

- **DLog #16 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-56 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (24 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `7516bd8`). Net-new symbols (10 listed: `AuditLog._persistence`, `AuditLog._pending_writes`, `AuditLog.attach_persistence`, `AuditLogPersistence` class, `AuditLogPersistence.start`/`stop`/`persist_entry`/`load_entries`/`count`, `EventType.AUDIT_PERSISTED`, `SecurityInfraConfig.audit_persistence_enabled`, `SecurityInfraConfig.audit_persistence_filename`, `runtime.audit_log_persistence`, `tests/test_ad456d_audit_log_persistence.py`) are intra-prompt-introduction (Sections 0 / 1 / 2a-d / 3 SEARCH/REPLACE). Same FP class as Waves 27-56.

- **DLog #17 — Test count target +14, ceiling +15.** 14 explicit tests in Section 4. The +15 ceiling allows one boundary discovery during build (Wave-30/39/41/42/53/55/56 precedent). If post-build delta is <+14 or >+15, hard-stop and triage before commit. Wave 56 baseline (11252) + 14 new = 11266 net target.

- **DLog #18 — Commercial-leak audit: clean.** AD-456d is OSS plumbing — a `ConnectionFactory`-backed persistence class + a transitional config flag + a fire-and-forget write hook + an EventType. AD-456d-5 *(Commercial)* deferral entry tags Postgres / cloud audit-storage adapters / federated audit aggregators / SOX-compliance archival as the extension-point seam — describes WHAT plugs in (extension point on the existing `protocols.ConnectionFactory` from AD-466), NOT business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #19 — No Wave-10 reframe trigger expected.** v1 scope is already minimal per pre-applied Wave-10 / wave-5 convention #3: per-append `create_task` instead of batched queue (AD-456d-2); shutdown-flush hook deferred (AD-456d-1); tamper-response policy deferred (AD-456d-3); default-flip deferred (AD-456d-4); retention deferred (AD-456d-6); HXI surface deferred (AD-456d-7); commercial overlays deferred (AD-456d-5). The Builder will hard-stop and surface ONLY if persistence-layer tests reveal that the existing AD-456 in-memory tests REGRESS — which they should not, because every additive field has a default and `append()`'s sync return path is unchanged. If a regression appears, most likely cause is Section 2c `__init__` hook ordering (e.g. `_pending_writes` field added without `field(default_factory=set)`).

## Highest-risk constraints (re-read before each Section)

1. **Section 2a `_persistence` and `_pending_writes` field insertion order in `AuditLog`.** Default-valued fields in a `@dataclass` must come AFTER non-defaulted fields. `AuditLog` has zero non-defaulted fields today (`entries` defaults to `field(default_factory=list)`, `emit_event` defaults to None, `GENESIS_HASH` is a class variable not an instance field), so insertion is safe. Both new fields use defaults — `_persistence: "AuditLogPersistence | None" = None` and `_pending_writes: set[asyncio.Task[Any]] = field(default_factory=set)`. SEARCH locks the entire class body so REPLACE is unambiguous.

2. **Section 2a forward reference to `AuditLogPersistence`.** `AuditLog` is defined BEFORE `AuditLogPersistence` in the same module. The type annotation MUST be quoted (`"AuditLogPersistence | None"`) OR the file must already use `from __future__ import annotations` (which it does — line 8). The annotation can be unquoted in the dataclass body because `from __future__ import annotations` makes all annotations lazy-evaluated. Builder: prefer unquoted (`AuditLogPersistence | None = None`) for readability since the file already imports the future-annotations behavior.

3. **Section 2b `attach_persistence` insertion site.** SEARCH locks the line immediately after `verify_chain()` method body close (`return True` at line 100) and the `def _hash` head (line 103). New method slots between the two — public surface goes BEFORE the underscore-private `_hash`. Test #2 directly calls `log.attach_persistence(persistence)` and asserts `log._persistence is persistence` — verifies the method is reachable and the field is set with no other side effects.

4. **Section 2c `append()` extension — order of operations.** New code runs AFTER the existing `if self.emit_event is not None:` AUDIT_RECORDED emit block (line 71-83) and BEFORE the `return entry` line (line 84). This is the existing append's only mutation point that survives the persist-task scheduling. SEARCH locks the entire `append()` body so REPLACE is unambiguous. If new code lands BEFORE the AUDIT_RECORDED emit, the order-of-events contract inverts (PERSISTED can race ahead of RECORDED — observer-confusing).

5. **Section 2c `try: asyncio.get_running_loop(); except RuntimeError:`.** The except clause MUST swallow `RuntimeError` only — any broader except hides programmer bugs. The recovery action is `logger.debug(...) ; return entry` — DEBUG level (not WARNING, not INFO) because no-loop is a correct, expected sync-test path; warning-level would be log-spam. Test #8 captures debug output via `caplog.set_level(logging.DEBUG)`.

6. **Section 2c task-tracking idiom.** `task = loop.create_task(self._persistence.persist_entry(entry))` followed by `self._pending_writes.add(task)` followed by `task.add_done_callback(self._pending_writes.discard)`. ALL THREE lines required. If any is omitted: missing `add` → discard fails silently; missing `add_done_callback` → set grows unboundedly; missing `loop.create_task` → coroutine warning + no execution. Test #7 awaits `asyncio.gather(*log._pending_writes)` after append; if `add` is missed, gather is a no-op and persist_entry never runs.

7. **Section 2d `AuditLogPersistence` is at MODULE level**, NOT nested inside `AuditLog`. Module-level definition lets tests import it directly (`from probos.security.audit import AuditLogPersistence`). SEARCH locks the trailing `def _hash` method body close (the existing module's last line) — REPLACE appends the new class after a blank-line separator. Module-level definition is required for the forward-reference annotation pattern (DLog #13 dataclass-fields-using-class-defined-later).

8. **Section 2d schema PRAGMA ordering.** `start()` body sequence: `connect → execute("PRAGMA journal_mode=WAL") → execute("PRAGMA busy_timeout=5000") → execute("PRAGMA synchronous=NORMAL") → executescript(_SCHEMA) → commit`. Mirrors `ClearanceGrantStore.start()` exactly (`clearance_grants.py:64-72`). Builder MUST NOT reorder — PRAGMAs before schema; commit after schema. Builder MUST NOT collapse to a single executescript (PRAGMAs and CREATE TABLE behave differently under transactional vs non-transactional execution).

9. **Section 2d `persist_entry` exception handling.** `try: INSERT + commit + emit AUDIT_PERSISTED; except Exception: logger.warning(..., exc_info=True)`. The except clause MUST swallow ALL exceptions — caller is `append()` running in a fire-and-forget task; an unhandled exception there would print an asyncio warning to stderr (noisy) and the task object's `.exception()` would carry the error (silently lost from the caller's perspective). The warning log is the visible failure signal. Test #11 forces an exception via a stub factory that raises on `execute` and asserts the log line + no propagation.

10. **Section 2d `load_entries` returns ordered list.** SQL `ORDER BY sequence ASC` REQUIRED. Without ORDER BY, SQLite is permitted to return rows in any order; the rehydrate would land entries with shuffled `sequence` values, breaking `verify_chain()` because the `prior_hash` chain depends on entry order. Test #6 inserts 5 entries, calls `load_entries`, and asserts `[e.sequence for e in loaded] == [0, 1, 2, 3, 4]`.

11. **Section 3 finalize block placement.** New if-block goes IMMEDIATELY AFTER the existing AD-456 AuditLog wiring (lines 1293-1297) and BEFORE the AD-456b RuntimeSandbox block (line 1300). SEARCH locks the entire `if config.security_infra.audit_enabled:` block (existing AD-456 wiring, lines 1293-1297) plus the trailing blank line. If the new block lands BEFORE the existing AD-456 wiring, `runtime.audit_log` is None at the `attach_persistence` call site — AttributeError.

12. **Section 3 finalize sequence.** Sequence MUST be: construct → `await persistence.start()` → `loaded = await persistence.load_entries()` → `if loaded: runtime.audit_log.entries.extend(loaded)` → `if loaded and not runtime.audit_log.verify_chain(): logger.warning(...)` → `runtime.audit_log.attach_persistence(persistence)` → `runtime.audit_log_persistence = persistence` → `logger.info(...)`. DLog #6 — attach_persistence MUST be the second-to-last step. If attach_persistence runs before extend, a misconfigured caller appending between the two steps would write rehydrated entries back to the DB (duplicate-key collision, log noise).

13. **Section 3 boot-failure containment.** The whole new if-block runs inside a `try: ... except Exception: logger.warning(..., exc_info=True)`. If the DB file is corrupt, the disk is full, or the schema migration fails, boot continues with `runtime.audit_log_persistence = None` (and runtime.audit_log remains the in-memory log). This mirrors the existing AD-456 CredentialStore extension block (`finalize.py:1252-1267`) try/except shape exactly. Test #13 tampers a row via direct SQL after first-run persist, then runs a second `start()` + `load_entries()` + `verify_chain()` cycle and asserts WARNING + non-blocked boot.

14. **Section 4 test isolation.** Tests use `tmp_path` fixture for SQLite DB files (auto-cleanup at test exit). No tests share `AuditLog` or `AuditLogPersistence` instances — each test calls `_make_log()` / `_make_persistence(tmp_path)` fresh. No tests leak class-level state (there is none). pytest-xdist parallel runs are safe.

15. **Test #7 (`test_append_with_persistence_attached_persists_via_task`) deterministic synchronisation.** Test runs an `async def` body, calls sync `log.append(...)` (which inside a running loop schedules `loop.create_task(persist_entry)`), then `await asyncio.gather(*log._pending_writes)`. Awaiting the explicit set guarantees the persist task has completed before `await persistence.count()` asserts the row landed. Without the gather, the count would be 0 with high probability (the test would race). Builder MUST use `asyncio.gather(*log._pending_writes)` — NOT `await asyncio.sleep(0)` (insufficient guarantee on multi-step coroutines).

16. **Do NOT touch `AuditEntry` dataclass.** Frozen, 6 fields, SHA-256 chain — the schema mirror depends on these exact 6 fields. Adding a `persisted: bool` field would break `verify_chain()` (`_hash` payload would include the new field, invalidating every existing entry's hash).

17. **Do NOT touch `verify_chain()`.** Read-only against `self.entries`; persistence is orthogonal to chain integrity.

18. **Do NOT touch `_hash()`.** Same reason.

19. **Do NOT modify the existing `AUDIT_RECORDED` emit path.** Existing 4 tests assert the emit fires synchronously from `append()` with the existing payload shape (`sequence`, `category`, `entry_hash`). New persist-task path is additive after the existing emit.

20. **Do NOT add a NEW pool, agent, module beyond the new test file.** No EventType beyond `AUDIT_PERSISTED`. No new Pydantic config class — fields append to existing `SecurityInfraConfig`.

21. **Do NOT wire `persistence.stop()` into runtime shutdown.** AD-456d-1 territory. v1 sets `runtime.audit_log_persistence` so the future hook can be a one-line addition; v1 ships start + persist_entry + load_entries + a stop() method that exists but is unwired in production runtime shutdown.

22. **Do NOT import `aiosqlite` directly into `audit.py`.** All DB access goes through the injected `connection_factory: ConnectionFactory`. Tests use `SQLiteConnectionFactory()` from `probos.storage.sqlite_factory`. This preserves the cloud-ready abstraction (AD-466) and matches every other AD-622 / AD-524 / AD-687 SQLite-backed module.

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #16, recurring from Waves 52-56). Manual verify-first pass: 24 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `7516bd8`. Net-new symbols (10 listed in DLog #16) are intra-prompt-introduction (Sections 0 / 1 / 2a-d / 3 SEARCH/REPLACE). Same FP class as Waves 27-56.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11252 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `events.py` adds `AUDIT_PERSISTED`
2. Section 1 — `config.py` `SecurityInfraConfig` adds `audit_persistence_enabled: bool = False` + `audit_persistence_filename: str = "audit_log.db"`
3. Section 2a — `audit.py` `AuditLog` adds `_persistence` + `_pending_writes` fields
4. Section 2b — `audit.py` `AuditLog.attach_persistence` method
5. Section 2c — `audit.py` `AuditLog.append` adds fire-and-forget persist hook
6. Section 2d — `audit.py` `AuditLogPersistence` class (start/stop/persist_entry/load_entries/count + schema)
7. Section 3 — `startup/finalize.py` wires construct → start → load → extend → verify → attach → set runtime attr
8. Section 4 — `tests/test_ad456d_audit_log_persistence.py` NEW (14 tests)
9. Run focused gate: `pytest tests/test_ad456d_audit_log_persistence.py tests/test_ad456_security_infrastructure.py tests/test_ad456b_runtime_sandboxing.py tests/test_ad456c_per_tier_credentials.py -v -n 0`
10. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `tests/test_ad456_security_infrastructure.py::TestAuditLog` (4 tests, lines 176-228) regresses after Section 2 lands. The change is strictly additive — `AuditLog` gains two defaulted dataclass fields, one method, and an additive block in `append()` that's a no-op when `_persistence is None`. If a regression appears, most likely cause is Section 2c `append()` SEARCH/REPLACE ordering wrong (new block landed BEFORE the AUDIT_RECORDED emit, OR the existing `return entry` line was deleted). SEARCH locks both anchors — verify the indentation and the surrounding context preserved exactly.

- An existing test in `tests/test_ad456b_runtime_sandboxing.py` regresses. AD-456b contracts are orthogonal — no symbol overlap with AD-456d. If a regression appears, the failure is most likely in `events.py` (Section 0 — verify `SANDBOX_CAPABILITY_DENIED` and `CREDENTIAL_TIER_DENIED` are preserved AND the new `AUDIT_PERSISTED` value is unique).

- An existing test in `tests/test_ad456c_per_tier_credentials.py` regresses. AD-456c contracts are orthogonal. Same triage as above.

- Pydantic config validation failure at startup (every test would fail). Section 1 SEARCH locks the existing `credential_tier_enforcement` field with its multi-line comment; REPLACE re-emits the existing field unchanged plus the two new fields. If the Builder accidentally overwrites the old field's default or comment, validation breaks. Verify that `credential_tier_enforcement: bool = False` survives the REPLACE.

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage per `.github/copilot-instructions.md` — re-run failing file at `-n 0` first. Section 4 tests use `tmp_path` (unique per test) for SQLite files — no file races. If parallel-only failures appear, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

- Phantom-API pre-check script remains broken (DLog #16) — non-blocker for THIS wave; cleanup AD remains pending.

- Test count delta < +14 OR > +15 — investigate before commit (drift signal).

- Test #7 races (`test_append_with_persistence_attached_persists_via_task`). If `count == 0` instead of `count == 1` post-gather, most likely cause is missing `task.add_done_callback(self._pending_writes.discard)` (causing pending_writes set to be cleared before gather sees the task) OR missing `self._pending_writes.add(task)` (gather sees an empty set). Verify Section 2c task-tracking idiom is intact (DLog #3 / risk constraint #6).

- `aiosqlite` imported into `audit.py` directly. v1 contract: all DB access via `connection_factory: ConnectionFactory`. If aiosqlite slips in, the cloud-ready seam breaks for AD-456d-5 commercial overlays. Verify Section 2d `AuditLogPersistence` imports only `from probos.protocols import ConnectionFactory, DatabaseConnection`.

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-456d CLOSED entry. (Note: AD-456c builder skipped this step in Wave 56; if precedent holds, the Captain may handle the tracker update separately. Builder should ATTEMPT the prepend; non-blocker if skipped.)
- `docs/development/roadmap.md` — flip AD-456d row to ✅ shipped under the AD-456 cluster; add deferral entries:
  - **AD-456d-1**: Shutdown-flush hook (`runtime.audit_log_persistence.stop()` wired into runtime shutdown sequence — pair with similar shutdowns).
  - **AD-456d-2**: Batched persist queue + drain loop (perf optimisation vs per-append `create_task`).
  - **AD-456d-3**: Tamper-on-rehydrate Captain-alert path (`EventType.AUDIT_TAMPER_DETECTED` + alert routing; today: log-WARNING only).
  - **AD-456d-4**: Default-flip of `audit_persistence_enabled` to True once AD-456d-1 lands.
  - **AD-456d-5** *(Commercial)*: Postgres / cloud audit-storage adapters / federated audit aggregators / SOX-compliance archival — extension point on the existing `protocols.ConnectionFactory` (already shipped AD-466).
  - **AD-456d-6**: Retention policy (TTL or row cap) + archival to ShipsArchive.
  - **AD-456d-7**: HXI inspection surface (`/audit list`, `/audit verify`, `/audit since <ts>` shell commands).
- `DECISIONS.md` — prepend AD-456d entry at top of Era V. (Same precedent caveat as PROGRESS.md.)

## Issues to close

GitHub MCP `issue_write` close on **#400** (expect EMU 403 same as Waves 31-56; Captain closes manually).

## Commit message

`AD-456d: Security infra AuditLog SQLite persistence (AuditLogPersistence + fire-and-forget persist hook) (+14 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #16, recurring from Waves 52-56). Builder cannot run the standard pre-check; manual verify-first pass already done at draft (24 verifying greps). Forcing function for a tooling-hygiene-AD logged but NOT scoped into this wave.

2. **One new runtime dep is the existing `aiosqlite`** (already a workspace dep for every other SQLite-backed store). v1 implementation imports `from probos.protocols import ConnectionFactory, DatabaseConnection` and `from probos.storage.sqlite_factory import SQLiteConnectionFactory` (the latter only in `startup/finalize.py`, not in `audit.py` itself per DLog #14 + risk constraint #22). No NEW workspace dep introduced.

3. **Test count baseline asserted at 11252.** Wave-56 dispatch projected exactly 11239 + 13 = 11252; commit `6b7b57c` landed at 11252. If pre-flight returns ≠ 11252, hard-stop and triage before dispatching Builder.

4. **Wave 57 envelope: single-AD, sequential, 4 sections + sub-edits across 1 substantially-extended module + 3 single-edit files + 1 new test file (~310 lines, 14 tests).** Larger envelope than Wave 56 (which was 1 substantially-extended module via 6 sub-edits, no new module class). Wave 57's `audit.py` extension adds a NEW class (~120 lines) plus three method-level extensions to `AuditLog`. Builder envelope: comparable to Wave 55 (which added a 225-line new module file).

5. **Strictly additive — zero existing-symbol modifications to AD-456 contract.** `AuditEntry` unchanged. `AuditLog.append()` signature + sync return + AUDIT_RECORDED emit unchanged. `AuditLog.verify_chain()` and `AuditLog._hash()` unchanged. New `_persistence` field defaults None; new `_pending_writes` field defaults empty set; new `attach_persistence()` method is opt-in. New `audit_persistence_enabled` config defaults False; new `audit_persistence_filename` config defaults to a sensible name. The migration is forward-compatible.

6. **No mid-wave reframe expected.** v1 scope is already minimal per Wave-10 / wave-5 convention #3 pre-application: shutdown flush is AD-456d-1 (DLog #19 forcing function); batched queue is AD-456d-2; tamper-response is AD-456d-3; default-flip is AD-456d-4; retention is AD-456d-6; HXI surface is AD-456d-7; commercial overlays AD-456d-5. All known scope-bloat targets are pre-deferred at the prompt level. If the Builder discovers that the `loop.create_task` call from sync `append()` requires modifying ≥1 existing AD-456 test path to maintain invariants, hard-stop and surface — that would be a Wave-10 trigger to defer the persist-on-append hook to AD-456d-2 and ship only the explicit `await persistence.persist_entry(entry)` path in v1.

7. **No commercial leak.** AD-456d is OSS plumbing: `AuditLogPersistence` class + `ConnectionFactory` injection + transitional config flag + fire-and-forget persist hook + EventType. AD-456d-5 *(Commercial)* deferral entry tags Postgres / cloud audit-storage / federated audit aggregators / SOX-compliance archival as the extension-point seam — describes WHAT plugs in (extension point on the existing `protocols.ConnectionFactory` from AD-466), NOT business model. v1 ships zero references to pricing, tier strategy, customer counts, competitive analysis, professional-services positioning, or demo scripts with sales framing. Commercial-leak audit: **clean**.

8. **Production caller-base for `AuditLog.append()` is currently ZERO.** All 4 existing callers are in `tests/test_ad456_security_infrastructure.py`. This means the fire-and-forget per-append `create_task` pattern faces ZERO production load today — the perf concerns that motivate AD-456d-2 (batched queue) are speculative against a hypothetical future caller surface, not against any real load. v1 ships the simplest correct pattern; AD-456d-2 layers optimisation when a real caller appears. The current zero-caller state is also why the deny-on-rehydrate-tamper boot-fail option (DLog #7) is correctly deferred to AD-456d-3 — there are no production audit facts to defend in v1.

9. **No coupling to `EarnedAgency` / `CredentialStore` / `EgressPolicy` / `RuntimeSandbox`.** AD-456d sits adjacent to the rest of the AD-456 cluster but is fully independent. It does not consult tier (AD-456c), egress policy (AD-456b), sandbox capability (AD-456b), or credential resolution (AD-395 / AD-456). The persistence layer is a pure storage seam over the existing in-memory hash chain. This independence is also why no existing AD-456-cluster test should regress.

10. **Schema lock.** The 6-column SQL schema mirrors the 6-field `AuditEntry` dataclass exactly. Future field additions to `AuditEntry` would force an SQLite ALTER TABLE migration (or schema-version bump). v1 explicitly does not introduce a schema-version table — the assumption is the dataclass is stable (which it has been since AD-456 v1, Wave 7). If AD-456d-3 (tamper-response policy) ever adds a `tamper_state: str` field to `AuditEntry`, that AD must also handle the SQL migration. Not v1 territory.
