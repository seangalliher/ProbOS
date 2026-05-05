# WAVE 63 DISPATCH — AD-635c v1 Clinical Telemetry: Circuit Breaker State History

**Wave id:** 63
**Single AD:** AD-635c
**Closes:** #392
**Baseline test count:** 11334 (post-Wave-62, commit `9158635`) → expected **11348** (+14 net), ceiling **+18**
**HEAD at draft:** `9158635`, working tree clean

## Summary

AD-635 v1 (Wave 60) shipped `ClinicalTelemetryService` with two read-only data domains: dream history and cross-agent chain traces. AD-635b (Wave 62, just landed) added optional SQLite persistence of the audit ring. Both deferrals from AD-635 v1 named **circuit breaker state history** (AD-635c) as the next data domain. The roadmap entry at `docs/development/roadmap.md:5960` defines the scope precisely:

> *"Expose circuit breaker trip history (not just current state) to clinical agents via `ClinicalTelemetryService`. Clinical need: identifying agents with recurring trips as candidates for Counselor intervention or LIMDU."*

Verified at HEAD `9158635`:

```
src/probos/cognitive/circuit_breaker.py:54    @dataclass class AgentBreakerState (state, trip_count, zone, zone_history, ...)
src/probos/cognitive/circuit_breaker.py:60    zone_history: list[tuple[str, float]] = field(default_factory=list)  # max 20 in-memory
src/probos/cognitive/circuit_breaker.py:280   def should_allow_think(self, agent_id: str) -> bool:  # OPEN→HALF_OPEN transition site
src/probos/cognitive/circuit_breaker.py:439   def check_and_trip(self, agent_id: str) -> bool:     # HALF_OPEN→CLOSED transition site
src/probos/cognitive/circuit_breaker.py:479   def _trip(self, agent_id: str, reason: str) -> None: # CLOSED|HALF_OPEN→OPEN transition site
src/probos/cognitive/circuit_breaker.py:380   def _update_zone(...)→tuple[CognitiveZone, CognitiveZone]:  # zone transition site
src/probos/cognitive/circuit_breaker.py:432   logger.info("AD-506a: Zone transition %s -> %s for %s", old, new, agent)
src/probos/cognitive/circuit_breaker.py:524   def get_status(self, agent_id: str) -> dict:  # already public, returns last 5 zone_history
src/probos/cognitive/circuit_breaker.py:540   def get_zone(self, agent_id: str) -> str
src/probos/cognitive/circuit_breaker.py:550   def get_all_statuses(self) -> list[dict]
src/probos/proactive.py:182                    self._circuit_breaker = CognitiveCircuitBreaker()
src/probos/proactive.py:312                    self._circuit_breaker = CognitiveCircuitBreaker(config=cb_config)
src/probos/proactive.py:318                    def circuit_breaker(self) -> CognitiveCircuitBreaker:  # @property — already public
src/probos/cognitive/clinical_telemetry.py:60  def __init__(self, runtime, *, audit_max_entries, audit_store=None) -> None:
src/probos/cognitive/clinical_telemetry.py:80  async def query_dream_history(...)
src/probos/cognitive/clinical_telemetry.py:127 async def query_agent_chain_traces(...)
src/probos/cognitive/clinical_telemetry.py:172 @property def audit_log(self) -> list[dict[str, Any]]:
src/probos/cognitive/clinical_telemetry.py:235 def _record_audit(...)→None
src/probos/config.py:2027                      class ClinicalTelemetryConfig(BaseModel):  # AD-635 / AD-635b
src/probos/config.py:2034-2037                 enabled, audit_max_entries, audit_persistence_enabled, audit_db_path
src/probos/config.py:1802                      class CircuitBreakerConfig(BaseModel):  # AD-506a — base thresholds (NOT touched by this AD)
src/probos/startup/finalize.py:550             def _wire_clinical_telemetry(*, runtime, config) -> bool:
src/probos/cognitive/clinical_audit_store.py   class ClinicalAuditStore — AD-635b reference shape (mirror exactly)
src/probos/protocols.py:223                    class ConnectionFactory(Protocol):
src/probos/cognitive/activation_tracker.py:60  connection_factory: Callable[..., Any] | None = None  # canonical pattern
DECISIONS.md (highest AD)                      AD-695 — AD-635c is unique
PROGRESS.md baseline                           11334 tests collected (post-Wave-62)
docs/development/roadmap.md:5960               AD-635c *(Scoped, OSS, Issue #392)*
```

**The gap closed by AD-635c:** the breaker's `zone_history` lives only in `AgentBreakerState.zone_history` (capped at 20 entries per agent, in-memory) and `state` mutations are not persisted at all. On restart, the entire trip / zone history evaporates. Clinical workflows that need to identify *recurring* trips for LIMDU candidacy or Counselor intervention have nothing to query — `get_status()` returns only current state plus the last 5 zone events, and only for as long as the runtime has been up. Operators investigating "did Khan trip the breaker three times this week?" are blind across restarts.

AD-635c v1 ships the producer + consumer in one Builder cycle:

1. **`CircuitBreakerHistoryStore` class** — new module `src/probos/cognitive/circuit_breaker_history_store.py`. SQLite-backed durable store for breaker state and zone transitions. Mirrors AD-635b/AD-542 `ConnectionFactory` pattern exactly (constructor accepts an optional `connection_factory` callable; default uses `aiosqlite.connect(db_path)`). Lazy `_ensure_open()` schema bootstrap. Public surface: `async append(entry: dict) -> None` and `async recent(limit: int, *, agent_id: str | None = None) -> list[dict]` (most-recent-first, optional agent filter). Schema:

   ```sql
   CREATE TABLE circuit_breaker_history (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       ts REAL NOT NULL,
       agent_id TEXT NOT NULL,
       transition_kind TEXT NOT NULL,   -- "state" or "zone"
       old_value TEXT NOT NULL,         -- e.g. "closed", "green"
       new_value TEXT NOT NULL,         -- e.g. "open", "amber"
       trip_count INTEGER NOT NULL DEFAULT 0,
       cooldown_seconds REAL NOT NULL DEFAULT 0.0,
       reason TEXT
   );
   CREATE INDEX idx_cbh_ts ON circuit_breaker_history(ts DESC);
   CREATE INDEX idx_cbh_agent_ts ON circuit_breaker_history(agent_id, ts DESC);
   ```

2. **`CognitiveCircuitBreaker` extension** — adds `history_store: "CircuitBreakerHistoryStore | None" = None` keyword to `__init__` (AD-635b shape), plus a public `set_history_store(store)` setter for late-bind wiring (the breaker is constructed inside `ProactiveCognitiveLoop.__init__` before clinical-telemetry wire time, so a late-bind seam is required — same shape as the late-bind `emit_event` field on `gap_aggregator` per AD-456 sibling pattern). Tracking set `self._write_tasks: set[asyncio.Task[None]] = set()`. Four hook points (each captures the *prior* state BEFORE mutation):

   - `_trip()` — records `transition_kind="state", old_value=<prior breaker state value>, new_value="open", trip_count=<post-increment>, cooldown_seconds=<post-compute>, reason=<reason str>`. Covers both `closed→open` (initial trip) and `half_open→open` (probe failure).
   - `should_allow_think()` — when transitioning OPEN→HALF_OPEN, records `transition_kind="state", old_value="open", new_value="half_open"`.
   - `check_and_trip()` — when HALF_OPEN→CLOSED recovery fires, records `transition_kind="state", old_value="half_open", new_value="closed"`.
   - `_update_zone()` — when `new_zone != old_zone`, records `transition_kind="zone", old_value=<old_zone.value>, new_value=<new_zone.value>, trip_count=<state.trip_count>`. The zone transition site already isolates `if new_zone != old_zone:` so the hook is a clean append at the end of that block.

   Each hook calls a single private `_record_transition(agent_id, **kwargs)` helper which builds the entry dict and calls `_schedule_history_write(entry)` — sync, fire-and-forget, no-loop-detected → DEBUG-log + skip (test fixture path), per AD-635b DLog #1.

3. **Two new `ClinicalTelemetryConfig` fields:**
   - `circuit_breaker_history_persistence_enabled: bool = False` — Wave-10 convention #14 transitional flag.
   - `circuit_breaker_history_db_path: str = "data/circuit_breaker_history.db"` — anchored under `data/` like `audit_db_path`.

4. **`ClinicalTelemetryService` extension:**
   - New `__init__` keyword: `circuit_breaker_history_store: "CircuitBreakerHistoryStore | None" = None`. Default None preserves AD-635 / AD-635b behavior bit-for-bit.
   - New public method:
     ```python
     async def query_circuit_breaker_history(
         self,
         *,
         requester_agent_id: str,
         target_agent_id: str | None = None,
         limit: int = 50,
     ) -> list[dict[str, Any]]:
     ```
     Same clearance gate (`_authorize_clinical_query`), same audit-ring write (`query_type="circuit_breaker_history"`, `target_agent_id` carried through), same return-empty-on-failure tier-2 log-and-degrade. Reads from `self._circuit_breaker_history_store.recent(limit, agent_id=target_agent_id)` when wired; returns `[]` when the store is None.

5. **`_wire_clinical_telemetry` extension** — double-gated, mirrors AD-635b. When both `cfg.enabled` AND `cfg.circuit_breaker_history_persistence_enabled` are True, construct `CircuitBreakerHistoryStore(db_path=cfg.circuit_breaker_history_db_path)`, pass it into `ClinicalTelemetryService.__init__` as `circuit_breaker_history_store=...`, AND stash it on `runtime.clinical_telemetry._pending_breaker_store` for the late-bind seam. The proactive-cognitive-loop wirer at `finalize.py:985+` runs AFTER the clinical wirer (`finalize.py:935`) and is the natural attach site: a small late-bind block immediately after `proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)` at line 1006 reads `runtime.clinical_telemetry._pending_breaker_store` (when present) and calls `proactive_loop.circuit_breaker.set_history_store(...)`. **Critical:** during `finalize_startup`, `runtime.proactive_loop` is NOT yet assigned — the runtime's main loop sets `self.proactive_loop = fin.proactive_loop` AFTER `finalize_startup` returns (verified at `runtime.py:1704`). The late-bind therefore uses the **local `proactive_loop` variable** inside the proactive block, not `runtime.proactive_loop`. Test #18 locks the late-bind path; tests #14/#15 indirectly cover the no-pending-store path via the clinical-service constructor default.

6. **Zero EventType additions.** State and zone transitions are already logged via `logger.info`/`logger.warning`; existing `EventType.CIRCUIT_BREAKER_TRIP` (events.py:123) is preserved unchanged and is a separate concern from history persistence.

7. **No restore-on-boot in v1.** The in-memory `zone_history` deque (capped at 20) starts empty after restart; the SQLite DB retains all historical rows. Operators query the DB directly: `sqlite3 data/circuit_breaker_history.db "SELECT * FROM circuit_breaker_history WHERE agent_id='khan-1' ORDER BY ts DESC LIMIT 20"`. **Deferred to AD-635c-1** (separate GH issue — Captain to file post-merge).

8. **No retention/rotation policy in v1.** Disk-side row growth is unbounded (in-memory zone_history is capped). At realistic transition frequency (~1 transition per active agent per hour during stress, much less under steady state), 14-crew over a year is roughly 122K rows — well within SQLite's comfort zone. **Deferred to AD-635c-2.**

9. **No structured payload column.** Schema is flat, six typed columns. Future signal kinds may want extra fields (`similarity_ratio`, `velocity_count`); those deserve a structured payload. **Deferred to AD-635c-4.**

10. **No modification of existing `get_status()`, `get_zone()`, `get_all_statuses()`, `get_last_zone_transition()`** on the breaker — all four AD-488 / AD-506a / AD-506b accessors stay byte-identical. All existing `tests/test_ad488_*.py`, `tests/test_ad506a_*.py`, `tests/test_ad506b_*.py` tests continue to pass unchanged.

One new test file (`tests/test_ad635c_circuit_breaker_history.py`, **14 tests** target / 18 ceiling). The 9 existing AD-635 v1 tests + 15 existing AD-635b tests in `tests/test_ad635_clinical_telemetry.py` and `tests/test_ad635b_anomaly_audit_persistence.py` continue to pass unchanged — Sections 0+1 are additive, Section 2 (breaker extension) uses keyword-only constructor extension and a NEW public setter (no signature change to existing callers — `proactive.py:182` and `:312` continue to work bit-for-bit), Section 3 (clinical service extension) uses keyword-only constructor extension and a NEW public method, Section 4 (finalize wirer) is double-gated by the new transitional flag.

Source-edit files: `config.py` additive (2 fields + docstring update), `cognitive/circuit_breaker_history_store.py` new file, `cognitive/circuit_breaker.py` constructor extension + 4 hook insertions + 4 new private helpers + 1 new public setter + 2 new instance attrs (`_history_store`, `_write_tasks`), `cognitive/clinical_telemetry.py` constructor extension (new keyword) + 1 new public query method, `startup/finalize.py` SEARCH/REPLACE on the existing `_wire_clinical_telemetry` body (~30 lines append) + late-bind block inserted inside the proactive-cognitive-loop block immediately after `proactive_loop.set_config(...)` (~16 lines).

Default-flip of `circuit_breaker_history_persistence_enabled` to True (after one operator-validated rehearsal cycle), restore-on-boot of the in-memory `zone_history` (AD-635c-1, separate GH issue — Captain to file post-merge), per-agent retention/rotation policy (AD-635c-2 — currently unbounded growth in SQLite), composite `(agent_id, ts)` index promotion to primary access pattern (AD-635c-3 — v1 ships the index but does not promote), structured JSONB-style payload column for transition-specific extras (AD-635c-4 — current schema is flat), and *(Commercial)* alternative storage backends for hosted deployments (AD-635c-5) are pre-deferred at the prompt level.

## Architect calls (Decision Log)

- **DLog #1 — Single store, two `transition_kind` values, NOT two tables.** A `CREATE TABLE state_transitions` + `CREATE TABLE zone_transitions` schema would be more "normalized" but the access patterns are identical (agent_id + ts), the column shapes are identical (id, ts, agent_id, old, new, optional fields), and the consumer-side `query_circuit_breaker_history` wants a UNIFIED time-ordered view (a clinician asking "what happened to Khan in the last hour" wants state AND zone events interleaved, not two separate queries). One table with `transition_kind TEXT NOT NULL` discriminator is the right shape. Test #5 / #6 lock both kinds in one query result.

- **DLog #2 — `_record_transition` hooks happen AFTER state mutation but BEFORE the existing logger.info call.** AD-635b DLog #11 locked "ring append BEFORE write-through" so a write-through failure leaves the in-memory state consistent. The breaker analog: state mutation FIRST (so `state.state = BreakerState.OPEN` is committed before any persistence side-effect), then the transition record is built using the *post-mutation* `state` plus a captured *prior* value, then write-through is scheduled. Tests #7 / #8 lock the ordering — a raise from the store does NOT prevent the breaker from transitioning.

- **DLog #3 — `set_history_store(store)` setter, NOT a constructor-only kwarg.** `CognitiveCircuitBreaker` is constructed at `proactive.py:182` with no args (default constructor) and at `proactive.py:312` with `config=cb_config`. The breaker is then held inside `ProactiveCognitiveLoop._circuit_breaker` for the lifetime of that loop. The clinical telemetry wirer runs BEFORE the proactive-loop wirer in `finalize_startup` call ordering — verified at `startup/finalize.py:935` (clinical) vs `:985` (proactive). A constructor-only kwarg would force coupling between proactive-cognitive config and clinical config, and would either require re-constructing the breaker (forfeit existing state) or threading the store through `set_config(...)` (which already takes 3 args — adding a 4th is a smell). The setter is one method, two lines (`self._history_store = store`), and can be called any time after construction. Mirrors the late-bind `emit_event` pattern in AD-456 / AD-530 sibling wirers. Tests #9 / #10 lock the setter contract.

- **DLog #4 — Hook on `_trip()` captures the prior state by reading `state.state` BEFORE mutation.** The current `_trip()` body sets `state.state = BreakerState.OPEN` at line 484. The hook insertion captures `prior_state_value = state.state.value` BEFORE that assignment, then issues `_record_transition(agent_id, transition_kind="state", old_value=prior_state_value, new_value="open", trip_count=state.trip_count, cooldown_seconds=state.cooldown_seconds, reason=reason)` AFTER the mutation completes. Test #7 asserts `closed→open` on first trip and `half_open→open` on probe-failure trip (pre-set state to HALF_OPEN, call `_trip` directly, verify `old_value == "half_open"`).

- **DLog #5 — Late-bind seam: stash-on-service THEN attach-inside-proactive-block.** The clinical wirer constructs `CircuitBreakerHistoryStore` and passes it to `ClinicalTelemetryService.__init__` (so the consumer-side `query_circuit_breaker_history` works regardless of proactive-loop state). The clinical wirer ALSO stashes the store on `service._pending_breaker_store`. The proactive-cognitive-loop block in `finalize_startup` (line 985+, gated by `config.proactive_cognitive.enabled and runtime.ward_room`) constructs `proactive_loop` as a local variable, calls `proactive_loop.set_config(..., cb_config=config.circuit_breaker, ...)` at line 1006 (this is where the breaker is re-instantiated with `cb_config`), and immediately after reads `runtime.clinical_telemetry._pending_breaker_store` and calls `proactive_loop.circuit_breaker.set_history_store(...)` if present. **Critical correctness note:** `runtime.proactive_loop` is NOT yet assigned during `finalize_startup` — the runtime's main loop assigns `self.proactive_loop = fin.proactive_loop` AFTER finalize_startup returns (verified at `runtime.py:1704`). The late-bind therefore uses the local `proactive_loop` variable. If proactive cognitive is disabled in config, the pending field is silently dead state on the clinical service — `query_circuit_breaker_history` reads from the empty (but valid) durable store directly. Tests #14 / #15 / #16 / #18 lock the branches.

- **DLog #6 — `query_circuit_breaker_history` accepts `target_agent_id: str | None = None`.** When None, the query returns ALL agents' transitions across the time range. When set, the query filters by agent. The audit ring records `target_agent_id=target_agent_id` (None when unfiltered). This matches the clinical use-case described in the roadmap entry: a Counselor reviewing fleet-wide breaker activity vs. a Medical drilling into a specific Engineer's recurring trips. Test #11 / #12 lock both branches.

- **DLog #7 — `recent(limit, *, agent_id=None)` keyword-only filter.** SQLite query: `SELECT ... FROM circuit_breaker_history WHERE agent_id = ? ORDER BY ts DESC LIMIT ?` when filtered, `SELECT ... FROM circuit_breaker_history ORDER BY ts DESC LIMIT ?` unfiltered. Composite index `idx_cbh_agent_ts` makes the filtered path O(log N + limit). Mirrors AD-635b `recent(limit)` shape. Test #4 / #5 / #6 lock the rows-back-most-recent-first contract; test #11 locks the agent_id filter; test #6 also asserts `limit=0 → []`.

- **DLog #8 — Write-through failure is tier-2 log-and-degrade.** A SQLite write failure (disk full, locked DB) MUST NOT propagate up through `_trip()`, `should_allow_think()`, or `_update_zone()` — these are HOT PATHS in the proactive loop. AD-635b DLog #7 set the precedent. Test #8 raises from `history_store.append`, asserts WARNING logged, asserts the breaker still transitions (subsequent `get_status` reflects the new state).

- **DLog #9 — `circuit_breaker_history_persistence_enabled: bool = False` default.** Wave-10 convention #14. Two transitional flags now hang off `ClinicalTelemetryConfig` (audit + breaker history); both default False. Default-flip to True scheduled as AD-635c-1.

- **DLog #10 — Storing the BREAKER state value (`closed`/`open`/`half_open`), NOT the BreakerState enum directly.** The store schema column `old_value TEXT` and `new_value TEXT` matches the existing `BreakerState.value` and `CognitiveZone.value` shape (lowercase strings). Test #5 asserts a state row stores `"closed"` / `"open"` / `"half_open"` and a zone row stores `"green"` / `"amber"` / `"red"` / `"critical"`. Single-source-of-truth: the enums already define the canonical strings.

- **DLog #11 — Two indexes (`ts DESC` + `agent_id, ts DESC`).** AD-635b DLog #6 had only the `ts DESC` index because the `recent(limit)` API was unfiltered. AD-635c needs the `(agent_id, ts DESC)` composite for the agent-filtered path; the `ts DESC` index stays for the unfiltered path. SQLite query planner picks correctly. Test #13 verifies BOTH indexes exist in `sqlite_master`.

- **DLog #12 — `query_circuit_breaker_history` audit-ring entry uses `query_type="circuit_breaker_history"` (no underscore variation).** Consistent with `"dream_history"` / `"chain_traces"` precedent in AD-635 v1 (`clinical_telemetry.py:97`/`:178`). Test #17 locks the audit-ring entry.

- **DLog #13 — Hook on `should_allow_think` records ONLY the OPEN→HALF_OPEN transition.** The method has three early-return branches: CLOSED (returns True, no transition), OPEN with cooldown elapsed (mutates to HALF_OPEN — record), OPEN with cooldown remaining (returns False, no transition), HALF_OPEN (returns True, no transition), and a defensive fall-through (no transition). Only the cooldown-elapsed branch produces a transition. The hook insertion is a single line immediately after `state.state = BreakerState.HALF_OPEN`, before the `logger.info(...)` call. Test #9 fast-forwards `time.monotonic` (or pre-sets `tripped_at` to a past value) to drive the OPEN→HALF_OPEN path and asserts the transition row.

- **DLog #14 — Hook on `check_and_trip` records ONLY the HALF_OPEN→CLOSED recovery.** The HALF_OPEN→OPEN re-trip path goes back through `_trip()` (covered by Hook #1). The HALF_OPEN→CLOSED branch is the existing `if state.state == BreakerState.HALF_OPEN:` block at lines 466-472. The hook insertion records the transition immediately after `state.state = BreakerState.CLOSED` and before the `logger.info(...)` recovery message. Test #10 drives this branch.

- **DLog #15 — `_update_zone` hook inside the existing `if new_zone != old_zone:` block.** The conditional already has `state.zone = new_zone; state.zone_entered_at = now; state.zone_history.append(...); ...; logger.info("AD-506a: Zone transition ...")`. The hook insertion is a single `self._record_transition(agent_id, transition_kind="zone", old_value=old_zone.value, new_value=new_zone.value, trip_count=state.trip_count)` call appended at the end of that block, before the `else: state.last_zone_transition = None`. Test #11 drives at least one GREEN→AMBER and one AMBER→RED transition (or asserts zone rows present after a `check_and_trip` cycle that crosses zones).

- **DLog #16 — No-loop branch at the schedule helper logs DEBUG and skips.** `asyncio.get_running_loop()` raises `RuntimeError` when called outside an event loop (test fixtures + sync-test paths). The `try/except RuntimeError` block in `_schedule_history_write` catches and `logger.debug("AD-635c: no running event loop; circuit-breaker history write skipped")` then returns. AD-635b DLog #1 sets the precedent. Test #18 asserts the no-loop branch produces NO history rows AND no exceptions.

- **DLog #17 — Wave-10 reframe NOT triggered.** Producer (4 hooks) + consumer (1 query method) ship together because they share the store. Both producer and consumer are tractable in one Builder cycle. Three deferrals (restore-on-boot, retention/rotation, composite-index promotion) are independently buildable concerns that fit the AD-635 deferral pattern. The prompt closes #392 cleanly because the roadmap-named scope — *"Expose circuit breaker trip history (not just current state) to clinical agents via `ClinicalTelemetryService`"* — is exactly satisfied: the breaker writes through to a durable store, the clinical service reads from it through a clearance-gated method.

- **DLog #18 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-62 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (24 verifying greps in this dispatch + the prompt's "Verified Against Codebase" table — all confirmed against HEAD `9158635`). Net-new symbols are intra-prompt-introduction (Sections 0+1+2+3+4) and listed exhaustively at the foot of the prompt: `CircuitBreakerHistoryStore` + 5 attrs/methods, `CognitiveCircuitBreaker.set_history_store` + 3 private helpers + 2 instance attrs (NOT a new ctor kwarg per DLog #3 — late-bind setter is the seam), `ClinicalTelemetryService.__init__` ctor kwarg `circuit_breaker_history_store` + `_circuit_breaker_history_store` instance attr + `query_circuit_breaker_history` method + `_pending_breaker_store` instance attr, `ClinicalTelemetryConfig.circuit_breaker_history_persistence_enabled` + `.circuit_breaker_history_db_path`. Same FP class as Waves 27-62.

- **DLog #19 — Test count target +14, ceiling +18.** Producer (8 tests for the breaker hooks + the store) + consumer (4 tests for the query method) + finalize (2 tests for double-gating + late-bind) = 14 baseline. Boundary discovery may add up to 4 more (granted-as-int storage, schema column types, no-loop branch, late-bind-skip-when-proactive-disabled). If post-build delta is <+14 or >+18, hard-stop and triage before commit.

- **DLog #20 — Commercial-leak audit: clean.** AD-635c is OSS plumbing — one new module, one keyword-only constructor parameter, one keyword-only constructor parameter on the clinical service, four breaker hooks, four private helpers, one public setter, one new clearance-gated query method, two Pydantic config fields, an additive finalize-block extension + late-bind block, 14 tests. AD-635c-5 *(Commercial)* deferral names alternative storage backends for hosted deployments — the public `CircuitBreakerHistoryStore` class with constructor-injected `connection_factory` IS the seam; the OSS plumbing is public. No pricing, revenue model, customer counts, professional-services positioning, competitive analysis, or GTM language. v1 ships zero references to any of those. Commercial-leak audit: **clean.**

## Builder workflow (standard)

1. Pre-flight gate: `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11334 collected at HEAD `9158635`.
2. Apply Sections 0 → 1 → 2 → 3 → 4 in order. Each section's SEARCH/REPLACE block is locked verbatim against HEAD.
3. After Section 1 (new file), run `python -c "from probos.cognitive.circuit_breaker_history_store import CircuitBreakerHistoryStore"` to confirm import path.
4. After Section 2 (breaker extension), run `pytest tests/test_ad488_*.py tests/test_ad506a_*.py tests/test_ad506b_*.py -n 0` to confirm existing breaker tests still pass.
5. After Section 3 (clinical service extension), run `pytest tests/test_ad635_*.py tests/test_ad635b_*.py -n 0` to confirm AD-635 v1 + AD-635b tests still pass.
6. Add Section 5 tests one at a time — confirm each passes before adding the next. The 14-test set is structured: tests 1-3 = config + store import; tests 4-8 = store CRUD + breaker hooks + write-through; tests 9-13 = full hook coverage + index/schema; tests 14-17 = clinical query method + audit ring + late-bind; test 18 = no-loop branch.
7. Final gate: `pytest tests/ -q -n 4 --dist=loadfile` → expect 11348 (+14 net target, +18 ceiling).
8. Update tracking: `PROGRESS.md` (append CLOSED entry), `docs/development/roadmap.md:5960` (flip Scoped→complete), `prompts/wave-plan.yaml` (id 63 → status: done).

## Hard-stop conditions

1. Test count delta lands outside [+14, +18]. → Triage which section(s) over- or under-shot.
2. Existing AD-488 / AD-506a / AD-506b / AD-635 / AD-635b tests fail. → Did Section 2 mutate breaker public surface? Did Section 3 mutate ClinicalTelemetryService public surface? Re-check verbatim SEARCH blocks.
3. `_record_transition` is on a hot path; if any benchmark test goes red, triage whether the in-process schedule-task overhead is the cause (mitigate: ensure `_history_store is None` short-circuits BEFORE `asyncio.get_running_loop()` to keep the no-persistence path free).
4. Real working-tree changes appear in source files NOT named in this dispatch. → Hard stop, surface to user.
5. Late-bind block runs INSIDE the `proactive-cognitive-loop` block — it executes only when `config.proactive_cognitive.enabled and runtime.ward_room` is True. When proactive cognitive is disabled, the block is skipped entirely; `_pending_breaker_store` remains stashed on the clinical service as harmless dead state. Test #16 locks the proactive-disabled path; test #18 locks the late-bind-success path.

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635c v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635b). |
| `docs/development/roadmap.md:5960` | Flip `*(Scoped, OSS, Issue #392)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook ConnectionFactory + late-bind sibling pattern application). |
| `prompts/wave-plan.yaml` (id: 63) | Set `status: done` post-archive. |
| GH issue #392 | Closed by Captain post-merge with commit hash. |
