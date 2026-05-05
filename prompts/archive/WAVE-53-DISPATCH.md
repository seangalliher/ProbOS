# WAVE 53 DISPATCH — AD-659c v1 Chain Optimizer Counselor Watchdog + Decision Persistence

**Wave id:** 53
**Single AD:** AD-659c
**Closes:** #410
**Baseline test count:** 11208 (Wave 52, commit `b91dafe`) → expected **11220** (+12 net)
**HEAD at draft:** post-Wave-52 (`b91dafe`, working tree clean, archive `b91dafe`)

## Summary

AD-659 (Wave 31) shipped analysis-only proposals. AD-659b (Wave 52) shipped the apply path + persistence + dedup + manual revert. AD-659c closes the deferred watchdog + decision-persistence half:

1. **Three new EventTypes** — `OPTIMIZATION_PROPOSAL_APPLIED` (emitted from `ChainOptimizer.apply_proposal()`), `OPTIMIZATION_PROPOSAL_REVERTED` (from `revert_proposal()` — covers both Captain and watchdog actors), `OPTIMIZATION_REGRESSION_DETECTED` (from the watchdog when post-apply success rate drops below the floor).
2. **`OptimizationCounselor` watchdog service** in new `cognitive/optimization_counselor.py` — subscribes to `OPTIMIZATION_PROPOSAL_APPLIED`, snapshots a pre-apply success-rate baseline, schedules a delayed check after `observation_window_seconds`, compares post vs baseline, persists every decision, optionally auto-reverts.
3. **Decision persistence** — new `optimization_decisions` SQLite table on `CognitiveJournal` (INSERT-only audit trail) plus `record_optimization_decision()` + `get_recent_optimization_decisions()` CRUD methods.
4. **Two-gate config** — `ChainOptimizerCounselorConfig.enabled` (default `False`) gates the watchdog at all; `auto_revert_enabled` (default `False`) is a SECOND gate so the Captain can run in observe-only mode before granting destructive authority.
5. **Async wirer** — `_wire_optimization_counselor` in `startup/finalize.py`; cascade slot inserted AFTER `_wire_chain_optimizer` (counselor depends on chain_optimizer being wired first).

p95 latency regression, Wilson-score confidence intervals, BridgeAlert routing, HXI surface, warm-boot timer replay, and `CounselorAgent.py` integration are explicitly deferred (see DLogs #2/#3/#5/#7).

## Architect calls (Decision Log)

- **DLog #1 — Standalone service, NOT a `CounselorAgent` method.** `CounselorAgent` is event-handler-saturated (~25 `_on_*` handlers at `counselor.py:932-1727`) and concerned with crew wellness — adding chain-tuning regression handling there would couple unrelated concerns. The watchdog runs as a sibling service (mirrors AD-695 `ThresholdAlertService` pattern). Zero `CounselorAgent` changes.

- **DLog #2 — Default-False on BOTH `enabled` AND `auto_revert_enabled`.** Wave-10 convention #14 applied twice. The first gate keeps the wave invisible at runtime until Captain opts in. The second gate lets Captain validate watchdog detection accuracy in observe-only mode (records decisions, emits `OPTIMIZATION_REGRESSION_DETECTED`, but never calls `revert_proposal`) before granting destructive authority. Mirrors AD-659b's `apply_enabled=False` two-stage adoption.

- **DLog #3 — Success rate only, no p95 latency.** v1 detects regression via success-rate drop (default 10% absolute floor over `observation_window_seconds`). p95 latency is more sensitive to per-step variance and needs a wider baseline window — deferred to AD-659c-1. Forcing function: AD-659c v1 ships and Captain reviews success-rate decisions in production.

- **DLog #4 — Three EventTypes, one Section 0 SEARCH/REPLACE.** All three new enum values inserted as a single block immediately after `MCP_BRIDGE_FAILED` (the last AD-449 entry, line 230) and before `OBSERVABILITY_SNAPSHOT_PUBLISHED` (line 231). Same pattern Wave 51 followed for AD-660b additions.

- **DLog #5 — No new BaseEvent dataclass.** All three new EventTypes are emitted via dict-payload `runtime.emit_event(EventType.X, {...})` — same shape as AD-660 (CausalReasoningEvent emission), AD-695 (ThresholdAlert emission), AD-449 (MCP_BRIDGE emission), AD-641a (OBSERVABILITY_SNAPSHOT emission). Structured `BaseEvent` subclasses are appropriate when downstream consumers need typed payload access; v1 has only the watchdog as a consumer (and it doesn't subscribe to its own emissions).

- **DLog #6 — INSERT-only `optimization_decisions` table (no upsert).** Each watchdog observation is a new row by design — the audit trail is the value. AD-659b's `optimization_proposals` table uses INSERT OR REPLACE because `proposal_id` is the natural PK that gets re-written on apply/revert; AD-659c's table has an AUTOINCREMENT `id` because `proposal_id` is FK-style (one proposal can have multiple decision rows if the watchdog ever re-evaluates — though v1 evaluates exactly once per `proposal_id`).

- **DLog #7 — Per-proposal idempotent watchdog.** `_pending_checks: dict[str, asyncio.Task]` tracks at most one in-flight watchdog per `proposal_id`. If the same id fires apply twice (re-event), the old task is cancelled (last-event-wins). Re-applying after revert is a NEW `proposal_id` (fresh `OptimizationProposal` instance via dedup-on-detector-target gate), not a re-arm of the same one — so the dict-key collision case is rare.

- **DLog #8 — Schema CREATE in `start()`, no warm-boot migration.** New table, no ALTER. Idempotent `CREATE TABLE IF NOT EXISTS` mirrors AD-659b's pattern at journal.py:192 exactly. Section 2 inserts the new `executescript` line immediately after AD-659b's.

- **DLog #9 — Async `_wire_optimization_counselor` (not sync).** Counselor's `start()` is async (subscribes via `runtime.add_event_listener` which may be async-tolerant; future-proof the wirer). AD-659b's `_wire_chain_optimizer` is sync because `start_scheduled_loop()` is sync. Different shapes for different lifecycles.

- **DLog #10 — Cascade slot inserted AFTER `_wire_chain_optimizer`.** Counselor subscribes to events emitted by ChainOptimizer; ChainOptimizer must be wired first or the subscription points at no emission source. Section 5 places the cascade invocation immediately after `_wire_chain_optimizer` and BEFORE `_wire_causal_reasoner` (line 880).

- **DLog #11 — `add_event_listener` shape verified.** `runtime.add_event_listener` exists at `runtime.py:683` (signature accepts callable + `event_types=` kwarg). The counselor's `start()` does `add_listener(self._on_apply_event_async, event_types=[EventType.OPTIMIZATION_PROPOSAL_APPLIED])` — same shape `CounselorAgent.initialize` uses at `counselor.py:670-707`.

- **DLog #12 — `_on_apply_event_async` tolerates two payload shapes.** Some runtime emit shapes pass `{"event_type": "...", "data": {...}}`; others pass the data dict directly. Counselor's handler reads `event.get("data", event)` to handle both — defensive against runtime emit-shape drift between test stubs and production.

- **DLog #13 — Cancellation-safe watchdog.** `_watchdog_check` catches `CancelledError` after `asyncio.sleep`, pops the proposal from `_pending_checks`, and re-raises. Standard async-context-cleanup pattern from `.github/copilot-instructions.md` Async Discipline section.

- **DLog #14 — Phantom-API pre-check could not be auto-run.** Same as Wave 52 DLog #14: `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error (terminator missing on line 342). Manual verify-first pass was performed at draft time — see prompt's "Verified Against Codebase" table (20 symbols + line numbers + verifying lines, all confirmed against HEAD `b91dafe`). Net-new symbols (`OPTIMIZATION_PROPOSAL_APPLIED`, `OPTIMIZATION_PROPOSAL_REVERTED`, `OPTIMIZATION_REGRESSION_DETECTED`, `optimization_decisions` table, `record_optimization_decision`, `get_recent_optimization_decisions`, `OptimizationCounselor`, `OptimizationDecision`, `ChainOptimizerCounselorConfig`, `_wire_optimization_counselor`, `runtime.optimization_counselor` attribute, `_compute_success_rate_window`, `_evaluate_and_record`, `_persist`, `_pending_checks`, `_listener_attached`) are all introduced by explicit SEARCH/REPLACE blocks or the new file body in Section 3 — same intra-prompt-introduction FP class as Waves 27-52. Tooling-hygiene-AD for the pre-check script remains a forcing function for a future wave.

## Highest-risk constraints (re-read before each Section)

1. **Section 5 cascade slot placement.** The wirer must run AFTER `_wire_chain_optimizer` (counselor subscribes to its events) and BEFORE `_wire_causal_reasoner`. The SEARCH block uses 2 lines (the `if _wire_chain_optimizer(...)` + `wired_phases.append("chain_optimizer")`) for unique anchoring; if the surrounding cascade has drifted, fall back to the NOTE FOR BUILDER block in Section 5.

2. **Section 1a/1b emission blocks are additive.** They append a new `if self.emit_event is not None:` block AFTER the existing `logger.info` and BEFORE `return proposal`. The SEARCH blocks include the entire `if journal is not None: ... return proposal` tail to ensure unique-match. Existing AD-659 + AD-659b tests must continue passing because they pass `emit_event=None` (verified at `tests/test_ad659b_chain_optimizer_apply.py` — opts using `ChainOptimizer(runtime, apply_enabled=True)` without `emit_event=`). When `emit_event=None`, the new emission block is a no-op.

3. **Section 2 schema execution sequence preserved.** New `_SCHEMA_OPTIMIZATION_DECISIONS` is added as a module-level constant immediately after `_SCHEMA_OPTIMIZATION_PROPOSALS`; in `start()`, the new `executescript` is inserted between AD-659b's `executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)` and the existing `commit()`. Idempotent `CREATE TABLE IF NOT EXISTS` — safe for warm-boot DBs that pre-date this AD.

4. **Section 4 field validators.** `ChainOptimizerCounselorConfig` adds three `@field_validator`s (window > 0, drop_floor in [0,1], min_samples >= 1). Test #12 validates each rejection path. Validators must be `@classmethod` decorated AFTER `@field_validator` (order matters in Pydantic v2 — verified pattern matches `ChainOptimizerConfig._validate_interval` at `config.py:359-362`).

5. **`runtime.add_event_listener` may be unavailable on stub runtimes.** `OptimizationCounselor.start()` checks `getattr(self._runtime, "add_event_listener", None)` and logs a WARNING + returns gracefully when None — preserves the test-stub-friendly contract used by 12 tests in Section 6.

6. **`runtime.config` shape for the counselor**: tests do NOT exercise the cfg-driven wiring path; tests instantiate `OptimizationCounselor(runtime, ...)` directly with `SimpleNamespace` runtime. This is intentional — wirer-side smoke is covered indirectly via Section 4 config-defaults test (#12). End-to-end wiring smoke is Section 5's responsibility but only the cascade-slot insertion is tested at the wirer level (defer end-to-end-with-real-config to AD-659c-1).

7. **Do NOT add a structured BaseEvent class for any of the three new EventTypes.** DLog #5. All emissions use dict payload via `runtime.emit_event(EventType.X, {...})` — same shape as AD-660 / AD-695 / AD-641a / AD-449 sibling AD precedents. AD-659b also did NOT add a BaseEvent class.

8. **Do NOT touch `CounselorAgent` (`cognitive/counselor.py`).** The counselor is event-handler-saturated and concerned with crew wellness; AD-659c watchdog is a chain-tuning concern that lives in its own service. Zero changes.

9. **Do NOT touch `routers/chain_optimizer.py`.** No new REST endpoint for watchdog decisions in v1; `journal.get_recent_optimization_decisions()` is the read surface. Captain-facing surfacing is AD-659c-2 (HXI).

10. **Do NOT add a new pool, agent, or module beyond `cognitive/optimization_counselor.py`.**

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #14). Manual verify-first pass: 20 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `b91dafe`. Net-new symbols (16 listed in DLog #14) are intra-prompt-introduction (Sections 0/1a/1b/2/3/4/5 SEARCH/REPLACE blocks + Section 3 new file). Same FP class as Waves 27-52. Forcing function for a tooling-hygiene AD remains noted but NOT scoped into this wave.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11208 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `events.py` adds 3 EventType values (single SEARCH/REPLACE block)
2. Section 1a — `chain_optimizer.py` `apply_proposal` emits `OPTIMIZATION_PROPOSAL_APPLIED`
3. Section 1b — `chain_optimizer.py` `revert_proposal` emits `OPTIMIZATION_PROPOSAL_REVERTED`
4. Section 2 — `journal.py` schema constant + `start()` execution + 2 CRUD methods
5. Section 3 — new `cognitive/optimization_counselor.py` (full file)
6. Section 4 — `config.py` `ChainOptimizerCounselorConfig` model + `SystemConfig` field
7. Section 5 — `startup/finalize.py` async `_wire_optimization_counselor` + cascade slot
8. Section 6 — new `tests/test_ad659c_optimization_counselor.py` (12 tests)
9. Run focused gate: `pytest tests/test_ad659c_optimization_counselor.py tests/test_ad659b_chain_optimizer_apply.py tests/test_ad659_chain_self_optimization.py -v -n 0`
10. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `test_ad659b_chain_optimizer_apply.py` or `test_ad659_chain_self_optimization.py` regresses after Section 1a/1b additive emit blocks land. The emission block is gated on `self.emit_event is not None` and existing tests pass `emit_event=None` — if a regression appears, the SEARCH/REPLACE landed wrong (e.g. missed the `is not None` guard).
- Section 5 cascade slot is inserted in the wrong order (counselor before chain_optimizer) — counselor's event subscription would fire against an unwired chain_optimizer. SEARCH anchor explicitly re-uses `_wire_chain_optimizer(...)` invocation line; if that pattern has drifted, fall back to the NOTE FOR BUILDER block.
- `runtime.add_event_listener` shape has changed since Wave 52 — counselor's `start()` would fail to attach. `_listener_attached=False` flag remains; the wirer logs WARNING and continues. Pre-build grep recommended:
  ```powershell
  d:/ProbOS/.venv/Scripts/python.exe -c "import subprocess; subprocess.run(['rg', '-n', 'def add_event_listener\\(', 'src/probos/runtime.py'])"
  ```
  Expected: 1 match at line 683 with signature `def add_event_listener(self, callback: Callable, *, event_types: list | None = None)`. If the signature drifts, hard-stop and surface to Architect (architectural decision required: change subscription kwarg shape OR use a different subscription surface).
- Phantom-API pre-check script remains broken (DLog #14) — non-blocker for THIS wave; cleanup AD remains pending.
- Test count delta < +12 OR > +13 — investigate before commit (drift signal). The +13 ceiling allows for 1 boundary-test discovery during build (precedent: Waves 30, 39, 41, 42 all over-shipped by 1-9 tests via fixture splits).
- Watchdog test (`test_evaluate_records_regression_and_reverts_when_auto_revert_enabled`) flaky on parallel xdist due to `asyncio.create_task` interaction — re-run at `-n 0` per the standing triage rule; if it only fails under parallel, mark as `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-659c CLOSED entry.
- `docs/development/roadmap.md` — flip AD-659c status to ✅ shipped; add AD-659c-1 / AD-659c-2 / AD-659c-3 deferral entries with explicit forcing functions.
- `DECISIONS.md` — prepend AD-659c entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#410** (expect EMU 403 same as Waves 31-52; Captain closes manually).

## Commit message

`AD-659c: OptimizationCounselor watchdog + decision persistence (+12 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #14, recurring from Wave 52). Builder cannot run the standard pre-check; manual verify-first pass already done at draft. Forcing function for a tooling-hygiene AD logged but NOT scoped into this wave.

2. **Section 1a + 1b are the only edits to a Wave-52-shipped file (`chain_optimizer.py`).** Both are strictly additive (new emission block before `return proposal`); existing tests use `emit_event=None` so emission is a no-op. If Builder discovers any regression in `tests/test_ad659b_chain_optimizer_apply.py` or `tests/test_ad659_chain_self_optimization.py`, the SEARCH/REPLACE landed wrong — hard-stop. Pre-build verification recommended:
   ```powershell
   d:/ProbOS/.venv/Scripts/python.exe -c "import subprocess; subprocess.run(['rg', '-n', 'self\.emit_event is not None|emit_event=None', 'src/probos/cognitive/chain_optimizer.py'])"
   ```
   Pre-build expected: 0 matches (the gate doesn't exist yet). Post-Section-1a: 1 match. Post-Section-1b: 2 matches. Existing test file matches: 0 (tests don't reference `emit_event`).

3. **Test count baseline asserted at 11208.** Wave-52 dispatch projected exactly 11198 + 10 = 11208; user-confirmed actual baseline post-Wave-52 is 11208 (commit `b91dafe`). If pre-flight returns ≠ 11208, hard-stop and triage before dispatching Builder.

4. **Wave 53 is single-AD, sequential, ~9 sections + new 460-line file (counselor) + new 280-line test file.** Comparable scope to Wave 52 (10 sections, +10 tests). No parallelization opportunity. Builder estimated time matches Wave 52 envelope.

5. **Two-gate config pattern** (`enabled` + `auto_revert_enabled`) is the principal Architect call. Same Wave-10 convention #14 applied twice — Captain validates watchdog observation accuracy in observe-only mode before granting destructive authority. This mirrors AD-659b's approach (`enabled` + `apply_enabled`) and means **boot with default config produces ZERO behavior change**.

6. **No mid-wave reframe expected.** All known scope-bloat targets — p95 latency detection, BridgeAlert routing, statistical confidence intervals, HXI surface, warm-boot timer replay, CounselorAgent integration — are pre-deferred at the prompt level (DLogs #2, #3, #5, #7 + "Out of scope" section). AD-659c-1 / AD-659c-2 / AD-659c-3 are the explicit forcing functions documented in the prompt body.

7. **No commercial leak.** AD-659c is OSS plumbing for a Captain-facing watchdog; commercial overlays for fleet-wide regression dashboards / multi-tenant audit / RBAC over decision rows would belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning.
