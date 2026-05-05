# WAVE 62 DISPATCH — AD-635b v1 Clinical Telemetry: Anomaly Audit Trail Persistence

**Wave id:** 62
**Single AD:** AD-635b
**Closes:** #391
**Baseline test count:** 11319 (post-Wave-61, commit `b2ecf20`) → expected **11331** (+12 net), ceiling **+15**
**HEAD at draft:** `b2ecf20`, working tree clean

## Summary

AD-635 v1 (commit history pre-Wave-62) shipped `ClinicalTelemetryService` with a **bounded in-memory audit ring** (`collections.deque(maxlen=audit_max_entries)`, default 1000). Every clearance-gated query call writes one row via `_record_audit(...)`; the ring is exposed read-only via the `audit_log` property. Audit entries are lost on restart — DD-6 of AD-635 explicitly deferred persistence to AD-635b: *"v1 in-memory only. Persistence deferred to AD-635b. Bounded prevents unbounded growth."*

Verified at HEAD `b2ecf20`:

```
src/probos/cognitive/clinical_telemetry.py:52   self._audit: collections.deque[dict[str, Any]] = collections.deque(maxlen=...)
src/probos/cognitive/clinical_telemetry.py:234  def _record_audit(... target_agent_id: str | None = None) -> None:
src/probos/cognitive/clinical_telemetry.py:252  self._audit.append(entry)
src/probos/cognitive/clinical_telemetry.py:172  def audit_log(self) -> list[dict[str, Any]]:
src/probos/config.py:2027                       class ClinicalTelemetryConfig(BaseModel):
src/probos/config.py:2034                           enabled: bool = False
src/probos/config.py:2035                           audit_max_entries: int = 1000
src/probos/startup/finalize.py:550              def _wire_clinical_telemetry(*, runtime, config) -> bool:
src/probos/startup/finalize.py:559                  runtime.clinical_telemetry = ClinicalTelemetryService(runtime, audit_max_entries=cfg.audit_max_entries)
src/probos/protocols.py:223                     class ConnectionFactory(Protocol):
src/probos/protocols.py:185                     class DatabaseConnection(Protocol):
src/probos/cognitive/activation_tracker.py:60   connection_factory: Callable[..., Any] | None = None,
src/probos/cognitive/activation_tracker.py:70   async def start(self) -> None: (lazy aiosqlite default)
docs/development/roadmap.md:5958                AD-635b *(Scoped, OSS, Issue #391)*
DECISIONS.md (highest AD)                       AD-689 — AD-635b is unique
```

**The gap closed by AD-635b:** the audit ring evaporates on every restart, defeating the "post-incident review" use case named in the roadmap entry. Operators investigating a clinical query series after a crash, restart, or stasis recovery have nothing to inspect.

AD-635b v1 ships:

1. **`ClinicalAuditStore` class** — new module `src/probos/cognitive/clinical_audit_store.py`. SQLite-backed durable store for audit entries. Follows the AD-542 / `ConnectionFactory` pattern (mirrors `ActivationTracker` in `cognitive/activation_tracker.py:55-79`). Constructor accepts an optional `ConnectionFactory` for cloud-ready storage substitution; default uses `aiosqlite.connect(db_path)` directly. Public surface: `async append(entry: dict) -> None` and `async recent(limit: int) -> list[dict]` (most-recent-first). Schema: `clinical_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, requester_agent_id TEXT NOT NULL, query_type TEXT NOT NULL, granted INTEGER NOT NULL, result_count INTEGER NOT NULL, target_agent_id TEXT)` plus index on `(ts DESC)`.

2. **Lazy initialization** — the SQLite connection opens on first `append(...)` call (via internal `async _ensure_open()` helper). The store can be constructed sync in `_wire_clinical_telemetry` without coordinating an async start phase — matches AD-635's "no automatic side effects until invoked" philosophy. Idempotent: a second `_ensure_open()` is a no-op once `self._db is not None`.

3. **`ClinicalTelemetryService` constructor extension** — adds `audit_store: ClinicalAuditStore | None = None` keyword parameter. When None, AD-635 v1 behavior is preserved exactly (in-memory ring only). When non-None, `_record_audit(...)` ALSO schedules a fire-and-forget task to write the entry through to the store. Stays sync (caller-API breakage forbidden — `_record_audit` is currently called inline from two async query methods, but the method itself is `def` not `async def`, and remains so).

4. **Fire-and-forget write-through** — mirrors AD-459b `set_stress_level` pattern from Wave 61. `_record_audit` calls `asyncio.get_running_loop()` inside try/except; on `RuntimeError` (no loop) it logs DEBUG and skips persistence (test-fixture path). On success, schedules `loop.create_task(self._write_through(entry))` and stores the task reference in `self._write_tasks: set[asyncio.Task]` with `add_done_callback(self._write_tasks.discard)` per Standing Order on async hygiene. The write itself is wrapped in tier-2 log-and-degrade — a SQLite-side failure NEVER propagates and NEVER prevents the in-memory `self._audit.append(entry)` from happening.

5. **Two new `ClinicalTelemetryConfig` fields:**
   - `audit_persistence_enabled: bool = False` — Wave-10 convention #14 (transitional flag, default-off until validated). v1 deployments boot identically to AD-635 v1; opt-in by setting True in YAML.
   - `audit_db_path: str = "data/clinical_audit.db"` — sensible default under the existing `data/` tree (`data/chroma.sqlite3` precedent at repo root).

6. **`_wire_clinical_telemetry` extension** — when both `cfg.enabled` AND `cfg.audit_persistence_enabled` are True, construct `ClinicalAuditStore(db_path=cfg.audit_db_path)` and pass via the new keyword. When `audit_persistence_enabled` is False, no store is constructed — `audit_store=None`, ring-only behavior. Logged at INFO when the store is wired.

7. **Zero EventType additions.** Audit persistence is not an event-emitting concern — `_record_audit` already runs once per query call.

8. **No restore-on-boot in v1.** The in-memory ring starts empty after restart; the SQLite DB retains all historical rows. Operators query the DB directly for post-incident review (`sqlite3 data/clinical_audit.db "SELECT * FROM clinical_audit ORDER BY ts DESC LIMIT 100"`). Restore-on-boot is **deferred to AD-635b-1**.

9. **No `ClinicalTelemetryService.query_audit_history(...)` method in v1.** A clinical-query-facade method that reads from the persistent store (vs. the in-memory ring property) is a separate API surface that interacts with the clearance gate; it is the natural home for an audit-of-audits clearance-tier check. **Deferred to AD-635b-2.** AD-635d (REST endpoints) will surface audit history via a separate endpoint — this is its concern, not ours.

10. **No modification of the `audit_log` property.** AD-635 v1's `audit_log` returns `list(self._audit)` from the in-memory ring; this stays unchanged. Tests for the ring-only path continue to pass.

One new test file (`tests/test_ad635b_anomaly_audit_persistence.py`, **12 tests** target / 15 ceiling). The 9 existing AD-635 v1 tests in `tests/test_ad635_clinical_telemetry.py` continue to pass unchanged — Section 0 (config) is additive, Section 1 (new module) is new, Section 2 (service constructor extension) is keyword-only with a default that preserves existing behavior, Section 3 (finalize wirer) is double-gated by the new transitional flag.

Source-edit files: `config.py` additive (2 fields + docstring update), `cognitive/clinical_audit_store.py` new file, `cognitive/clinical_telemetry.py` constructor extension + `_record_audit` extension + 2 new private helpers + 2 new instance attrs, `startup/finalize.py` SEARCH/REPLACE on the existing `_wire_clinical_telemetry` body (~12 lines append).

Default-flip of `audit_persistence_enabled` to True (after one operator-validated rehearsal cycle), restore-on-boot of the in-memory ring (AD-635b-1, separate GH issue — Captain to file post-merge), `query_audit_history(*, requester_agent_id, since=None, limit=100)` clearance-gated SQLite reader (AD-635b-2, separate GH issue), audit-row retention/rotation policy (AD-635b-3 — currently unbounded growth in SQLite; ring keeps in-memory size capped, but disk is not), structured JSONB-style payload column for query-specific extra fields (AD-635b-4 — current schema is flat), and *(Commercial)* alternative storage backends for hosted deployments (AD-635b-5) are pre-deferred at the prompt level.

## Architect calls (Decision Log)

- **DLog #1 — `_record_audit` stays sync; write-through is fire-and-forget.** Promoting `_record_audit` to async would force every caller (the two async query methods + future test fixtures + AD-635c/d/e/f follow-ups that are likely also internal callers) to `await` the write. The Builder is tempted to do this for "correctness". Don't. Mirrors AD-459b DLog #1 (Wave 61) — the sync surface is preserved by deferring async work via `loop.create_task(...)`. Tests for write-through use `asyncio.run(...)` to give the audit a running loop; sync test paths exercise the no-loop branch.

- **DLog #2 — Lazy SQLite init via `_ensure_open()`, NOT eager `start()`.** Matches AD-635's "nothing materialized until invoked" pattern (DD of AD-594a / AD-647b). Finalize stays synchronous; the store is constructed but the file isn't created until the first audit row writes. Critical for two reasons: (a) finalize is sync and adding an async-start coordination would be cross-cutting noise, (b) deployments that enable persistence but never have a clinical query run pay zero cost. The lazy init is idempotent — `if self._db is not None: return` short-circuits subsequent calls. Tests #4 / #5 lock the lazy semantics.

- **DLog #3 — `ConnectionFactory` keyword param on `ClinicalAuditStore`.** Mirrors `ActivationTracker.__init__` pattern (`activation_tracker.py:60`). Default None → uses `aiosqlite.connect(db_path)` inline. Commercial overlays (Postgres / Cosmos) inject a custom factory without changing call sites. This is the cloud-ready storage seam mandated by `.github/copilot-instructions.md`. Test #6 exercises a custom factory to lock the seam.

- **DLog #4 — Schema is flat, not JSONB-style.** Six typed columns (id, ts, requester_agent_id, query_type, granted, result_count, target_agent_id NULL). Future query types may want extra fields (`tier`, `dataset_size`, `latency_ms`); those deserve a structured payload column. Deferred to AD-635b-4. v1 schema covers exactly the keys `_record_audit` writes today: `ts`, `requester_agent_id`, `query_type`, `granted`, `result_count`, optional `target_agent_id`. Verified at `clinical_telemetry.py:266-277`.

- **DLog #5 — `granted` stored as INTEGER (0/1), not BOOLEAN.** SQLite has no native bool; convention across ProbOS stores (rejection_cache, persistent_tasks) uses INTEGER. Test #7 asserts the column type via `PRAGMA table_info(clinical_audit)`.

- **DLog #6 — Index on `(ts DESC)`, single column.** Most-recent-first is the dominant access pattern (AD-635d REST will paginate by recency, AD-635b-2 query method will too). Composite index over `(requester_agent_id, ts)` is tempting but premature — the table is bounded by query frequency (~10s of rows per crew per day), and `audit_max_entries=1000` is the in-memory cap; SQLite cap is unbounded but realistic working-set is small. Defer composite to AD-635b-3 if retention policy + per-agent query becomes hot. Test #8 verifies the single-column index exists.

- **DLog #7 — Write-through failure is tier-2 log-and-degrade.** A SQLite write failure (disk full, locked DB, schema mismatch from a downgrade) MUST NOT propagate up through `_record_audit` — the in-memory ring still gets the row (it appended BEFORE the task was scheduled, by line ordering in the REPLACE block), so the immediate clinical workflow is unaffected. Test #9 raises from `audit_store.append`, asserts WARNING logged, asserts the in-memory ring still contains the entry, asserts the calling query method does NOT raise.

- **DLog #8 — `audit_persistence_enabled: bool = False` default.** Wave-10 convention #14. AD-635 v1's `enabled` flag already defaults False (the entire service is invisible OOTB). The persistence flag is double-gated: even when the SERVICE is enabled, persistence requires a second opt-in. Operators flip both. Default-flip to True scheduled as AD-635b-0 once one rehearsal validates write-through under realistic clinical-query load.

- **DLog #9 — Finalize wirer is double-gated.** Both `cfg.enabled` AND `cfg.audit_persistence_enabled` must hold for the store to be constructed and injected. Don't collapse this — the two gates have different meanings: the SERVICE flag is "whether clinical queries work at all", the PERSISTENCE flag is "whether their audit is durable". Test #10 / #11 lock both branches (service-disabled = no store, service-enabled-but-persistence-disabled = no store, both-enabled = store wired).

- **DLog #10 — `audit_db_path` default `"data/clinical_audit.db"`.** Matches the convention of other ProbOS SQLite paths anchored under `data/` at repo root. Configurable via YAML for environments with different mount layouts. NOT made absolute in the default — the runtime's working directory at startup is the repo root by ProbOS convention. Don't default to an absolute path; that would break developer workstations.

- **DLog #11 — `_record_audit` ordering: append-to-ring FIRST, then schedule write.** The current AD-635 v1 line `self._audit.append(entry)` is the LAST line of the method. AD-635b's REPLACE places the schedule-task call AFTER the ring append, so a write-through failure (tier-2) leaves the ring in the same state as before the change — no regression. Tests #9 / #12 lock the ordering.

- **DLog #12 — No `start()` method on the service.** `ClinicalTelemetryService` is not a lifecycle subsystem (it's not registered with `DegradationManager`, doesn't have a background loop, doesn't open resources at construction). The store has lazy-open via `_ensure_open()`, and the service holds the store; no service-level `start()`/`stop()` is needed. Adding one would be over-engineering and would invite calls to `runtime.start()` to track yet another resource. Conformance with the "no Demeter chain" rule: when finalize calls `runtime.shutdown()`, an explicit clinical-store close hook can be added in AD-635b-1 (restore-on-boot AD) where the boot/shutdown surface is naturally needed.

- **DLog #13 — Audit-store lifecycle on shutdown.** The lazy-opened SQLite connection has no explicit `close()` call in v1. Python's GC closes file handles on process exit; in-flight write-through tasks complete (or are cancelled) when the runtime stops. This is acceptable for v1 (worst case: an in-flight write is lost from the ring's tail; the disk file is consistent because SQLite WAL handles the transaction boundary on commit). Explicit close is part of the AD-635b-1 restore-on-boot work where the lifecycle surface formalizes. v1 ships with a documented gap (test #12 documents that pending tasks may not flush before shutdown).

- **DLog #14 — Wave-10 reframe NOT triggered.** v1 ships the producer (write-through path) in one Builder cycle. Three deferrals (restore-on-boot, query_audit_history method, retention policy) are independently buildable consumer-side concerns that fit the AD-635 deferral pattern (where the parent shipped 2 of 4 domains and closed the parent issue). Closing #391 with v1 is correct because the roadmap entry text — *"Persist the in-memory audit ring (`ClinicalTelemetryService._audit` deque) to SQLite for post-incident review"* — is exactly satisfied by the write-through path. Post-incident review = `sqlite3 data/clinical_audit.db <query>` from a forensic shell. The follow-up ADs (audit-history method, REST surfacing, retention) extend the capability but the roadmap-named scope is complete.

- **DLog #15 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-61 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (16 verifying greps in this dispatch + the prompt's "Verified Against Codebase" table — all confirmed against HEAD `b2ecf20`). Net-new symbols (8 listed: `ClinicalAuditStore` class, `ClinicalAuditStore.append`, `ClinicalAuditStore.recent`, `ClinicalAuditStore._ensure_open`, `ClinicalTelemetryService.__init__` ctor kwarg `audit_store`, `ClinicalTelemetryService._write_through`, `ClinicalTelemetryConfig.audit_persistence_enabled`, `ClinicalTelemetryConfig.audit_db_path`) are all intra-prompt-introduction (Section 0 + 1 + 2). Same FP class as Waves 27-61.

- **DLog #16 — Test count target +12, ceiling +15.** 12 explicit tests in Section 4 plus boundary-discovery headroom. If post-build delta is <+12 or >+15, hard-stop and triage before commit. Wave 61 baseline (11319) + 12 new = 11331 net target.

- **DLog #17 — Commercial-leak audit: clean.** AD-635b is OSS plumbing — one new module (`cognitive/clinical_audit_store.py`), one keyword-only constructor parameter, two private helpers, two Pydantic config fields, an additive finalize-block extension, 12 tests. AD-635b-5 *(Commercial)* deferral names alternative storage backends for hosted deployments as the extension-point seam — the public `ClinicalAuditStore` class with constructor-injected `ConnectionFactory` IS the seam; the OSS plumbing is public. Pricing, revenue model, customer counts, professional-services positioning, competitive analysis, GTM language all belong in the private commercial repo. v1 ships zero references to any of those. Commercial-leak audit: **clean.**

- **DLog #18 — Anti-misclassification audit.** Five sibling AD-635b/c/d/e/f children exist as separate Wave-62 through Wave-66 entries in `prompts/wave-plan.yaml`. AD-635b is the **persistence-only** root — it MUST NOT (a) bundle circuit-breaker history (AD-635c, Wave 63, #392); (b) bundle REST endpoints (AD-635d, Wave 64, #393); (c) bundle shell command (AD-635e, Wave 65, #394); (d) bundle proactive-context injection (AD-635f, Wave 66, #395); (e) preempt the AD-635b-1 restore-on-boot follow-up; (f) preempt the AD-635b-2 audit-history-query method. Single AD = single deferral root = single GH issue (#391). Audit: clean.

- **DLog #19 — Distinct from AD-456d (Security AuditLog Persistence).** AD-456d (`docs/development/roadmap.md:4148`, issue #400) ships SQLite persistence for the **security inference audit** (AD-456 v1 layer). AD-635b ships persistence for the **clinical query audit** (AD-635 v1 layer). Same architectural pattern (`ConnectionFactory` + lazy init + write-through), different store class, different schema, different consumer service. The roadmap entry for AD-456d explicitly says *"Same persistence pattern as AD-635b (clinical audit ring)"* — AD-635b is the precedent. Builder MUST NOT touch `src/probos/security/` or `src/probos/audit/` paths; that is AD-456d's territory.

- **DLog #20 — Distinct from AD-466 (Engineering Infrastructure / StorageBackend).** AD-466's `StorageBackend` ABC (`src/probos/infrastructure/storage_backend.py`) is a higher-level seam over `ConnectionFactory` for runtime-wide store registration. AD-635b uses `ConnectionFactory` directly (the lower seam) because the audit store is a leaf that doesn't need the StorageBackend's discovery/registration machinery. This is the same choice activation_tracker, identity, mesh/routing, consensus/trust, and acm made — direct `ConnectionFactory` injection. No use of `StorageBackend` in v1.

## Highest-risk constraints (re-read before each Section)

1. **`_record_audit` MUST stay synchronous.** The Builder is tempted to `async def _record_audit` because the new write-through is awaitable. Resist this. Use `asyncio.create_task(...)` from inside the sync body. If `asyncio.get_running_loop()` raises (sync test outside an event loop), catch `RuntimeError` and skip task scheduling with a DEBUG log — the in-memory ring append still happens. Section 2 SEARCH/REPLACE locks the existing sync signature.

2. **In-memory ring append MUST happen BEFORE write-through scheduling.** The current AD-635 v1 line `self._audit.append(entry)` ordering is preserved. The Builder appends `_schedule_write_through(entry)` AFTER it. Reordering would mean a write-through-side failure (or no event loop) leaves the ring without the entry. Test #12 locks the ordering by mocking write-through to raise and asserting the ring still contains the entry.

3. **`audit_persistence_enabled` defaults False.** This is a Wave-10 convention #14 transitional flag. Default-True would silently activate SQLite writes on every existing deployment that boots Wave 62 — operators must opt in. Default-True is the AD-635b-0 follow-up after rehearsal.

4. **Finalize wirer is double-gated.** Both `cfg.enabled` AND `cfg.audit_persistence_enabled` must hold. Don't collapse into a single check — different meanings (service-on vs. persistence-on). Tests #10 / #11 lock both branches.

5. **`ClinicalAuditStore.__init__` does NOT open the SQLite connection.** Lazy `_ensure_open()` is the discipline. Constructor stores `db_path` and the optional `connection_factory`. Calling `ClinicalAuditStore(db_path="/tmp/x.db")` MUST NOT touch disk. Test #4 asserts `os.path.exists(db_path) is False` immediately post-construction.

6. **`ClinicalTelemetryConfig` extension keeps the docstring contract.** The existing docstring says "v1 is read-only, has no automatic invocation". Update to reflect AD-635b's addition (persistence is OFF by default; opt-in via `audit_persistence_enabled`). SEARCH locks the existing docstring + the two existing fields verbatim; REPLACE re-emits the class declaration + updated docstring + the two new fields after the existing ones.

7. **No modification of `audit_log` property.** Returns the in-memory ring snapshot exactly as today. Tests in `test_ad635_clinical_telemetry.py::test_service_shape_and_module_constants` assert `svc.audit_log == []` post-construction; AD-635b must not break this.

8. **No new EventTypes.** Audit persistence is not event-emitting. Don't add `EventType.AUDIT_PERSISTED` or similar — out of scope.

## Pre-flight (before Section 0)

```pwsh
git status
git log -1 --oneline    # expect: b2ecf20
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q --co 2>&1 | Select-Object -Last 3   # expect: 11319 tests collected
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad635_clinical_telemetry.py -q -n 0  # expect: 9 passed
```

If any check fails: hard-stop, surface to Captain.

## Per-section build/test cycle

After each section's edits:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad635_clinical_telemetry.py tests/test_ad635b_anomaly_audit_persistence.py -q -n 0
```

Sections 0-3 should leave the existing 9 AD-635 tests green; Section 4 introduces the new 12 tests. After all sections:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected delta: **+12 to +15 net** (target +12). If <+12 or >+15, hard-stop and triage:

- **<+12:** Builder shipped fewer tests than spec. Audit Section 4.
- **>+15:** Builder added boundary tests (acceptable up to +15). Document in build report.
- **Failures in `test_ad635_clinical_telemetry.py`:** Section 2 broke the AD-635 v1 contract (likely the constructor extension or `_record_audit` ordering). Hard-stop, revert Section 2, re-read DLog #1 / #11.

## Hard-stop conditions

1. `_record_audit` signature changed to `async def`. Revert and re-read DLog #1.
2. `ClinicalAuditStore.__init__` opens SQLite eagerly (touches disk). Revert and re-read DLog #2.
3. `audit_persistence_enabled` shipped as default True. Revert and re-read DLog #8.
4. `audit_log` property modified or its return shape changed. Revert.
5. New EventType added. Revert and re-read DLog #7 of this dispatch + the "No new EventTypes" highest-risk-constraint #8.
6. Modification of `src/probos/security/`, `src/probos/audit/`, or `src/probos/infrastructure/storage_backend.py`. v1 changes are bounded to `config.py` + `cognitive/clinical_audit_store.py` (new) + `cognitive/clinical_telemetry.py` + `startup/finalize.py`. Revert and re-read DLog #19 / #20.
7. Pre-existing AD-635 v1 tests fail. Hard-stop, surface to Captain.
8. Tests need >2 fix-loop iterations to pass. Hard-stop, surface to Captain.
9. Bundling AD-635c (circuit-breaker history), AD-635d (REST), AD-635e (shell), or AD-635f (proactive injection) into this AD. Revert and re-read DLog #18.

## Tracking updates (post-build, pre-commit)

1. **PROGRESS.md** — append `AD-635b v1 CLOSED.` paragraph mirroring the Wave 61 / Wave 60 shape.
2. **docs/development/roadmap.md:5958** — flip `*(Scoped, OSS, Issue #391)*` to `*(complete)*` per AD-695 / AD-647c precedent.
3. **DECISIONS.md** — NOT modified by this AD per Captain memory rule "only when explicitly required by the prompt"; AD-635b is not a cross-AD architectural inflection (it's the textbook application of the AD-542 `ConnectionFactory` pattern to a leaf store).
4. **prompts/wave-plan.yaml** — `id: 62` `status:` field set to `done` after archive.
5. **GH issue #391** — closed by Captain post-merge with commit hash.

## Acceptance Criteria

1. Test count delta lands in [+12, +15] inclusive.
2. All 9 existing AD-635 v1 tests pass unchanged.
3. All 12+ new AD-635b tests pass.
4. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) passes with new total in [11331, 11334].
5. `ClinicalAuditStore` is importable from `probos.cognitive.clinical_audit_store` with `append` and `recent` async methods plus optional `ConnectionFactory` constructor injection.
6. `ClinicalTelemetryConfig.audit_persistence_enabled` defaults False; `ClinicalTelemetryConfig.audit_db_path` defaults `"data/clinical_audit.db"`.
7. `ClinicalTelemetryService.__init__` accepts `audit_store: ClinicalAuditStore | None = None` keyword; default None preserves AD-635 v1 behavior bit-for-bit.
8. `_record_audit` writes the entry to the in-memory ring FIRST, THEN schedules a fire-and-forget write-through task when `self._audit_store is not None` and an event loop is running.
9. With `audit_persistence_enabled=False`, finalize constructs `ClinicalTelemetryService(runtime, audit_max_entries=...)` (no `audit_store`); existing AD-635 v1 wiring is unchanged.
10. With `audit_persistence_enabled=True` AND `enabled=True`, finalize constructs `ClinicalAuditStore(db_path=cfg.audit_db_path)` and passes via `audit_store=`.
11. No modification of `audit_log` property, `query_dream_history`, `query_agent_chain_traces`, or any `EmergentDetector` accessor.
12. No new EventType added.
13. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
14. Pre-commit deletion sanity check: max ~10 deletions any single file (config.py 1 / clinical_telemetry.py ~3 / startup/finalize.py ~5 line replace). Well below the 200-line surprise-deletion threshold.

## Single AD prompt

Builder reads `prompts/ad-635b-anomaly-audit-v1.md` next. That file is the authoritative spec; this dispatch is the wave-level framing.
