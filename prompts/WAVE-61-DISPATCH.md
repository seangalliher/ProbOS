# WAVE 61 DISPATCH — AD-459b v1 Saucer Separation: Active Shedding Hooks

**Wave id:** 61
**Single AD:** AD-459b
**Closes:** #396
**Baseline test count:** 11304 (post-Wave-60, commit `8fa370f`) → expected **11316** (+12 net), ceiling **+15**
**HEAD at draft:** `8fa370f`, working tree clean

## Summary

AD-459 v1 (Wave 6) shipped the saucer-separation read-only coordinator: `DegradationManager` (public on `runtime.degradation_manager`), `ServiceTierRegistry` (11 seed classifications: 5 ESSENTIAL / 3 COGNITIVE / 3 NON_ESSENTIAL), `SheddingPolicy` (NORMAL→{} / ELEVATED→NON_ESSENTIAL / HIGH+CRITICAL→NON_ESSENTIAL+COGNITIVE), and 2 EventTypes (`SERVICE_TIER_DEGRADED`, `SERVICE_TIER_RESTORED`). v1 surfaces `is_shed(name)` / `is_tier_shed(tier)` for subsystems to **self-poll**, and emits transition events. **It does not actively pause anything** — the responsibility is pushed onto each subsystem to consult `is_shed(...)` from inside its own loop.

Verified at HEAD `8fa370f`:

```
src/probos/degradation/manager.py:60      def set_stress_level(self, level: StressLevel) -> None:
src/probos/degradation/manager.py:74      def is_shed(self, service_name: str) -> bool:
src/probos/degradation/registry.py:35-49  _DEFAULT_CLASSIFICATIONS includes "dream_scheduler" + "proactive_loop" as COGNITIVE
src/probos/degradation/policy.py:35-45    HIGH and CRITICAL share shed mask in v1
src/probos/startup/finalize.py:1188-1200  always-wired construction of runtime.degradation_manager
src/probos/cognitive/dreaming.py:2774     class DreamScheduler
src/probos/cognitive/dreaming.py:2816     def start(self) -> None  (sync)
src/probos/cognitive/dreaming.py:2824     async def stop(self) -> None
src/probos/proactive.py:146               class ProactiveCognitiveLoop
src/probos/proactive.py:454               async def start(self) -> None
src/probos/proactive.py:460               async def stop(self) -> None
src/probos/runtime.py:210                 dream_scheduler: DreamScheduler | None
src/probos/runtime.py:230                 proactive_loop: ProactiveCognitiveLoop | None
```

**The gap closed by AD-459b:** subsystems that should shed under stress (`DreamScheduler`, `ProactiveCognitiveLoop`) currently keep running their `_think_loop`/`_consolidation_loop` regardless of degradation level — they don't yet poll `is_shed(...)`. Pushing that responsibility to every subsystem author is fragile and inconsistent. AD-459b inverts the contract: subsystems **register** with the manager, the manager **invokes** their `pause()` / `resume()` callbacks on tier transitions. The subsystem authors no longer need to know about degradation at all — they only need to expose a lifecycle.

AD-459b v1 ships:

1. **`SheddableSubsystem` Protocol** — new module `src/probos/degradation/subsystem.py`. Defines `runtime_checkable Protocol` with two async methods: `async def pause(self) -> None` and `async def resume(self) -> None`. Both methods MUST be idempotent (calling pause on a paused subsystem is a no-op; same for resume). The Protocol is the contract — concrete adopters can be classes, but most subsystems already have async `start()`/`stop()` (or sync `start()` + async `stop()`), so direct adoption requires no subsystem code change.

2. **`LifecycleAdapter`** — concrete helper in the same module that wraps existing `start()` / `stop()` methods to satisfy the Protocol. Constructor: `LifecycleAdapter(name: str, *, on_pause: Callable[[], Any], on_resume: Callable[[], Any])`. Both callables may be sync or async — adapter dispatches via `asyncio.iscoroutinefunction(...)` (BF-254 pattern). Tracks `_paused: bool` to enforce idempotency so the manager can re-emit transitions without double-stop. This is the canonical adoption path for `DreamScheduler` and `ProactiveCognitiveLoop`.

3. **`DegradationManager.register_subsystem(service_name, subsystem)`** — new public method. Validates that `service_name` is already classified in the registry (raises `ValueError` if not — the manager refuses to manage an un-classified subsystem, since it would not know which tier mask gates the lifecycle). Stores in `self._subsystems: dict[str, SheddableSubsystem]`. Replacing an existing registration logs a WARNING and returns the new instance (mirrors `ProcessChainRegistry.register_chain` from AD-647b and `ToolRegistry.register`). Returns `None`.

4. **`DegradationManager.unregister_subsystem(service_name) -> bool`** — Demeter-friendly remover. Returns False on absent (no exception). Returns True on successful removal.

5. **`DegradationManager.registered_subsystems() -> list[str]`** — read-only inspector returning sorted service names. Tests assert against this; HXI/observability tools could surface it later.

6. **`DegradationManager.set_stress_level(level)` extension** — stays **synchronous** (no caller-API breakage). After computing the transition delta, when `auto_pause_enabled` is True, schedules **fire-and-forget tasks** via `asyncio.create_task(self._invoke_pause(name, subsystem, tier))` and `_invoke_resume(...)` for every registered subsystem whose tier crosses into / out of the shed mask. The manager holds `self._lifecycle_tasks: set[asyncio.Task]` and uses `task.add_done_callback(self._lifecycle_tasks.discard)` per Standing Order. Each invocation is wrapped in try/except → `logger.warning(...)` (Tier-2 log-and-degrade); a subsystem-side exception NEVER propagates. On success, emits `EventType.SUBSYSTEM_PAUSED` / `SUBSYSTEM_RESUMED` with payload `{"service": name, "tier": tier.value, "stress_level": level.value}`.

7. **Two new EventTypes:** `SUBSYSTEM_PAUSED = "subsystem_paused"` and `SUBSYSTEM_RESUMED = "subsystem_resumed"`. Inserted in `events.py` immediately after the existing `SERVICE_TIER_RESTORED` row (anchor verified at draft).

8. **`DegradationConfig` extension** — adds one transitional flag: `auto_pause_enabled: bool = False`. Default-False per Wave-10 convention #14 (transitional-flag default-off until validated). v1 wires the registration in `finalize.py` only when this flag is True; default ProbOS deployment runs identically to AD-459 v1 read-only behavior. Captain flips to True after observing one stress-level cycle in a non-production rehearsal.

9. **Finalize wirer extension** — extends the existing AD-459 block at `startup/finalize.py:1188-1200`. After constructing `runtime.degradation_manager`, when `config.degradation.auto_pause_enabled` is True AND each candidate subsystem is non-None, register adopters: `dream_scheduler` (sync `start` + async `stop`) and `proactive_loop` (async `start` + async `stop`). Both `start`/`stop` methods already idempotent — `LifecycleAdapter` adds the `_paused` boolean wrap. Adoption logged at INFO. When the flag is False, no registration happens — collision-free with AD-459 v1.

10. **No modification of `DreamScheduler` or `ProactiveCognitiveLoop`.** Both classes keep their existing `start()` / `stop()` surface unchanged. The adapter wraps them at finalize time. Subsystem authors do not need to learn about saucer separation. This is the architectural value of AD-459b — the contract inversion.

11. **No modification of `EmergenceMetricsEngine`, `EmergentLeadershipDetector`, or `RedTeamLead`.** All three are classified NON_ESSENTIAL in the registry seed, so a transition to ELEVATED would shed them under AD-459 v1's read-only signal. None of the three has a clean `start()` / `stop()` lifecycle today (verified — they are on-demand / scan-based, not background loops). Adopting them requires either (a) introducing a "skip when shed" guard inside each scan path, or (b) adding lifecycle methods. Both are subsystem-specific work that belongs in dedicated sub-ADs. v1 ships hooks for the **two subsystems with proven lifecycle** and **defers the other three to AD-459b-1 / -2 / -3** with explicit GH issue tracking.

12. **No new public attribute on runtime.** `runtime.degradation_manager` already exists; `register_subsystem(...)` is a method on it. No `runtime.subsystem_registry` is introduced — the registry IS the manager (single coordinator pattern; a separate registry would be split-brain).

One new test file (`tests/test_ad459b_active_shedding.py`, **12 tests** target / 15 ceiling). Existing 13 AD-459 v1 tests in `tests/test_ad459_saucer_separation.py` continue to pass unchanged — Section 1 (config) is additive, Section 2 (Protocol module) is new, Section 3 (manager extension) preserves the existing `set_stress_level` shape (sync, NORMAL default, transition emit), Section 4 (events) is additive, Section 5 (finalize) is gated by default-False flag.

5 source-edit files: `events.py` additive (2 enum values), `config.py` additive (1 field), `degradation/subsystem.py` new file, `degradation/manager.py` additive (3 public methods + 2 private `_invoke_*` helpers + `_subsystems` + `_lifecycle_tasks` ctor init), `degradation/__init__.py` re-export additive, `startup/finalize.py` SEARCH/REPLACE on the existing AD-459 block (~10 lines append).

Default-flip of `auto_pause_enabled` to True (after the two-subsystem fleet rehearsal completes), `EmergenceMetricsEngine` adoption (AD-459b-1, separate GH issue), `EmergentLeadershipDetector` adoption (AD-459b-2), `RedTeamLead` adoption (AD-459b-3), capability gate on `register_subsystem` so only privileged callers register adopters (AD-459b-4), audit-chain emission on every pause/resume (AD-459b-5), AD-469 EPS-driven auto stress-level escalation (AD-459b-6, depends on AD-469b agent→department resolver), per-subsystem pause timeout + force-cancel (AD-459b-7), HXI subsystem-state surface (AD-459b-8), and a commercial overlay for SLA-graded shedding (per-tenant subsystem priorities, regulator-facing degradation evidence chain) are pre-deferred at the prompt level to AD-459b-1 through -8 and AD-459b-9 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — `set_stress_level` stays sync; subsystem hooks are fire-and-forget tasks.** Promoting `set_stress_level` to async would break every existing caller (verified zero external async-await callers at HEAD; the current ones are sync test fixtures and the prospective AD-469b EPS-coordinator hook). Sync→async promotion is a Wave-10 reframe-eligible change but unnecessary here: the manager already runs inside an async runtime, `asyncio.create_task(...)` is the cleanest way to invoke async subsystem methods from a sync caller, and storing the task references in `self._lifecycle_tasks` with `add_done_callback(...)` discharge satisfies the Standing Order on fire-and-forget tasks. Wave-5 retro #2 / #14 honored.

- **DLog #2 — `register_subsystem` rejects unknown service names with `ValueError`, NOT log-and-degrade.** Programming error, not runtime degradation. If finalize tries to register a subsystem whose name is not in the registry, the operator deployed an inconsistent system and should fail fast at boot. Mirrors `ProcessChainRegistry.register_bill_chain` AD-647c precedent (mismatched bill_step_id → ValueError, chain not registered). Test #6 locks the rejection.

- **DLog #3 — `register_subsystem` replaces with WARNING, NOT rejection.** Mirrors `ToolRegistry.register` (AD-423a) and `ProcessChainRegistry.register_chain` (AD-647b) precedents. Useful for hot-reload, test isolation, and finalize-rerun semantics. Test #7 locks the WARNING via `caplog`.

- **DLog #4 — `unregister_subsystem(unknown) -> False` not exception.** Demeter-friendly. Mirrors `ProcessChainRegistry.unregister_chain`. Test #8 locks.

- **DLog #5 — `LifecycleAdapter` dispatches via `asyncio.iscoroutinefunction(callable)`, NOT `asyncio.iscoroutine(result)`.** BF-254 lesson: `iscoroutinefunction` inspects the function before invocation; `iscoroutine` inspects the result after. With `MagicMock` (test fixture) the function is not a coroutine function but the result of calling it is also not a coroutine — the right gate is the function-side `iscoroutinefunction` check. Sync callables get called directly; async callables get awaited. Tests #1 / #2 cover both paths with both real callables and `AsyncMock` / `MagicMock` fixtures.

- **DLog #6 — `LifecycleAdapter` enforces idempotency via internal `_paused` bool.** `pause()` on already-paused: no-op + DEBUG log. `resume()` on already-running: no-op + DEBUG log. Critical for safety: a stress-level cycle (NORMAL→HIGH→NORMAL) emits one pause + one resume per subsystem; a flapping condition (NORMAL→HIGH→NORMAL→HIGH) must not double-stop a subsystem whose `stop()` is not re-entrant. `DreamScheduler.start()` and `ProactiveCognitiveLoop.start()` already early-return on existing task (verified at `dreaming.py:2820` and `proactive.py:455`), but the adapter belt-and-suspenders this guarantee. Tests #3 / #4 lock idempotency.

- **DLog #7 — `auto_pause_enabled: bool = False` default.** Wave-10 convention #14 (transitional flag default-off). v1 ships the wiring; Captain validates the contract by manually calling `runtime.degradation_manager.set_stress_level(StressLevel.HIGH)` in a rehearsal, observing `SUBSYSTEM_PAUSED` events, then confirming both subsystems resume cleanly on NORMAL. Default-flip to True scheduled as AD-459b-0 once rehearsal evidence is captured. The flag gates the **registration** in `finalize.py` — when False, the manager has zero registered subsystems and `set_stress_level` is functionally identical to AD-459 v1.

- **DLog #8 — `set_stress_level` invokes pause/resume by tier-mask delta, not by subsystem-tier identity.** When the tier transitions into the shed mask, every registered subsystem **classified into that tier** gets a pause task. Iteration: for each shed-newly tier, walk `self._subsystems` and check `self._registry.get_tier(name) == tier`. This means a subsystem registered under `dream_scheduler` (COGNITIVE) is NOT paused on NORMAL→ELEVATED (only NON_ESSENTIAL is shed there) but IS paused on NORMAL→HIGH (NON_ESSENTIAL + COGNITIVE both shed). Test #10 / #11 lock the per-level behavior.

- **DLog #9 — `SUBSYSTEM_PAUSED` / `SUBSYSTEM_RESUMED` emitted per-service, NOT per-tier.** Distinct from the tier-level `SERVICE_TIER_DEGRADED` / `SERVICE_TIER_RESTORED` emitted by AD-459 v1. Per-service granularity is necessary because different subsystems in the same tier may pause at different real-times (await ordering), and a future audit chain (AD-459b-5) needs per-subsystem rows. Payload includes `service`, `tier`, and `stress_level` so consumers can correlate without joining against the registry. Test #12 locks the payload shape.

- **DLog #10 — Pause exception → `logger.warning` + `SUBSYSTEM_PAUSED` NOT emitted.** Tier-2 log-and-degrade applies to the side-effect, not the event. If `subsystem.pause()` raises, the manager logs the failure with `exc_info=True` and skips the event emit — the subsystem is in an unknown state, and emitting `SUBSYSTEM_PAUSED` would lie to consumers. The next stress-level transition will retry. Test #13 raises from `LifecycleAdapter.pause()`, asserts WARNING logged, asserts `emit_event` NOT called for the failing subsystem (other subsystems' transitions still emit normally).

- **DLog #11 — Finalize wires DreamScheduler via `runtime.dream_scheduler`; ProactiveCognitiveLoop via the LOCAL `proactive_loop` variable.** Verify-first caught a real ordering subtlety: `runtime.dream_scheduler` IS set before finalize.py:1188 (assigned at runtime.py:1516 during the dreaming phase, BEFORE `finalize_startup` is invoked at runtime.py:1698). But `runtime.proactive_loop` is NOT set at finalize.py:1188 — it is assigned in runtime.py:1704 from `fin.proactive_loop` AFTER `finalize_startup` returns. Inside `finalize_startup`, the live binding is the local `proactive_loop` variable declared at line 863 and assigned at line 985. The Section 5 REPLACE block uses `runtime.dream_scheduler` for the dream adopter and the local `proactive_loop` for the proactive adopter. Each adopter is registered independently; tests #14 / #15 lock both branches (both registered when flag True + both subsystems live; zero adopters when flag False).

- **DLog #12 — No modification of `DreamScheduler.start/stop` or `ProactiveCognitiveLoop.start/stop`.** Both already idempotent. `LifecycleAdapter._paused` provides the pause/resume semantics. Adoption is purely additive at finalize. Critical for the "subsystem authors don't need to know about degradation" architectural value.

- **DLog #13 — `EmergenceMetricsEngine`, `EmergentLeadershipDetector`, `RedTeamLead` deferred.** All three are classified in `_DEFAULT_CLASSIFICATIONS` as NON_ESSENTIAL but do not currently expose `start()` / `stop()` lifecycle (verified). Adopting them requires either (a) wrapping their on-demand entry points with a "shed gate" (each scan checks `runtime.degradation_manager.is_shed("name")` before doing work) — the AD-459 v1 self-poll model, which AD-459b is INVERTING; or (b) introducing real lifecycle methods. Both options are subsystem-specific architectural decisions. v1 ships the framework + 2 proven adopters; deferred adopters are tracked in dedicated GH issues (AD-459b-1 / -2 / -3). Captain memory rule "DO NOT defer scope unless really necessary" is honored — the framework + 2 adopters IS the v1 scope; the additional 3 adopters require non-trivial subsystem refactor and are correctly out of scope.

- **DLog #14 — Wave-10 reframe NOT triggered.** v1 ships the Protocol + adapter + manager extension + 2 adopters in one Builder cycle. Reframe was considered for the sync-vs-async `set_stress_level` question (DLog #1) and rejected — fire-and-forget tasks preserve the sync API at zero correctness cost. No portion of the v1 scope is deferrable without breaking the AD's value (a Protocol with no adopters is theater). Captain memory rule: "DO NOT defer scope unless really necessary" — honored.

- **DLog #15 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-60 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (16 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `8fa370f`). Net-new symbols (10 listed: `SheddableSubsystem` Protocol, `LifecycleAdapter` class, `DegradationManager.register_subsystem`, `DegradationManager.unregister_subsystem`, `DegradationManager.registered_subsystems`, `DegradationConfig.auto_pause_enabled`, `EventType.SUBSYSTEM_PAUSED`, `EventType.SUBSYSTEM_RESUMED`, plus the two ctor kwargs `on_pause`/`on_resume` on `LifecycleAdapter`) are all intra-prompt-introduction (Section 0 + 1 + 2 + 3 + 4). Same FP class as Waves 27-60.

- **DLog #16 — Test count target +12, ceiling +15.** 12 explicit tests in Section 6 plus boundary-discovery headroom. If post-build delta is <+12 or >+15, hard-stop and triage before commit. Wave 60 baseline (11304) + 12 new = 11316 net target.

- **DLog #17 — Commercial-leak audit: clean.** AD-459b is OSS plumbing — one new module (`degradation/subsystem.py`), 3 new public methods on `DegradationManager`, 1 new Pydantic config field, 2 new EventTypes, an additive finalize-block extension, 12 tests. AD-459b-9 *(Commercial)* deferral entry tags SLA-graded shedding (per-tenant subsystem priorities, multi-region degradation aggregation, regulator-facing pause/resume evidence chain) as the extension-point seam — describes WHAT plugs in (the public `register_subsystem` method + per-subsystem EventType payload), NOT the business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #18 — Anti-misclassification audit.** No prior `AD-459a` artifact exists at HEAD `8fa370f` (verified: zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md` for the literal string `AD-459a`). The user's anti-misclassification clause is a forward-looking constraint: this prompt MUST NOT (a) re-scope AD-459b as a sub-letter — it's the b-tier root closing #396; (b) bundle EmergenceMetricsEngine / EmergentLeadershipDetector / RedTeamLead adoption into this AD; (c) bundle AD-469b EPS-driven escalation into this AD; (d) silently introduce a new top-level AD number outside the 459-cluster naming. Single AD = single deferral root = single GH issue (#396). Audit: clean.

- **DLog #19 — Distinct from AD-466 (Engineering Infrastructure).** AD-466 owns backup/restore, storage abstraction, and observability export. AD-459b owns subsystem pause/resume on degradation. They are orthogonal: AD-466 is about durability of state; AD-459b is about availability of compute. Test set explicitly avoids any AD-466 assertions; finalize wirer change is bounded to the AD-459 if-block.

- **DLog #20 — Distinct from AD-469 / AD-617b (token / EPS budgets).** AD-469's `EPSCoordinator.check_budgets()` is a budget-strain signal; AD-695's `ThresholdAlertService` is the operator-facing alert path. Neither currently writes to `runtime.degradation_manager.set_stress_level(...)` — that auto-escalation is AD-459b-6 work. v1 ships ONLY the manual / Captain-driven stress-level transition path. The auto-escalation gate is one method call away (`set_stress_level(StressLevel.HIGH)`) once AD-459b-6 lands; today the manual path is the test rehearsal path.

## Highest-risk constraints (re-read before each Section)

1. **`set_stress_level` MUST stay synchronous.** The Builder is tempted to `async def set_stress_level` because the new pause/resume calls are awaitable. Resist this. Use `asyncio.create_task(...)` in the body. If `asyncio.get_running_loop()` raises (caller invoked from sync test outside an event loop), catch `RuntimeError` and skip the task scheduling with a DEBUG log — tests use `asyncio.run(...)` to drive the manager (see Section 6 fixture pattern). Section 3 SEARCH/REPLACE locks the existing sync signature; the REPLACE re-emits `def set_stress_level(self, level: StressLevel) -> None:`.

2. **`register_subsystem` rejects unknown service names with `ValueError`.** The Builder is tempted to log-and-degrade (consistent with the rest of the manager). Don't. Programming error, not runtime degradation. Test #6 explicitly asserts `pytest.raises(ValueError, match="not classified")`.

3. **`auto_pause_enabled` defaults False.** This is a Wave-10 convention #14 transitional flag. Default-True would silently activate pause/resume on every existing deployment that boots Wave 61 — operators must opt in. Default-True is the AD-459b-0 follow-up after rehearsal.

4. **Finalize-wirer registration is double-gated.** Both `auto_pause_enabled` AND non-None subsystem must hold. Don't collapse this into a single check — the two gates have different meanings: the flag is operator policy, the None-check is runtime state. Tests #14 / #15 lock both branches.

5. **EventType insertion anchor in events.py.** SEARCH must lock `SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459` plus the line below it (a blank line + the next AD-491 EventType section start). REPLACE re-emits the AD-459 row + the two new AD-459b rows + the same blank line + the AD-491 anchor. Do NOT delete or move any existing EventType.

6. **`DegradationConfig` extension keeps the docstring contract.** The existing docstring says "v1 has no operator-tunable fields". Update the docstring to reflect AD-459b's addition. SEARCH locks the empty class body verbatim; REPLACE re-emits the class declaration + updated docstring + the new field.

7. **`degradation/__init__.py` is currently a 1-line module docstring file.** Verify-first confirmed (`read_file` on the file shows a single docstring). The Section 4 edit appends `from probos.degradation.subsystem import LifecycleAdapter, SheddableSubsystem` (or equivalent) so consumers can `from probos.degradation import LifecycleAdapter` without reaching into the submodule. This is additive only — no SEARCH/REPLACE needed (just append).

## Pre-flight (before Section 1)

```pwsh
git status
git log -1 --oneline    # expect: 8fa370f
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q --co 2>&1 | Select-Object -Last 3   # expect: 11304 tests collected
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad459_saucer_separation.py -q -n 0  # expect: 13 passed
```

If any check fails: hard-stop, surface to Captain.

## Per-section build/test cycle

After each section's edits:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad459_saucer_separation.py tests/test_ad459b_active_shedding.py -q -n 0
```

Sections 1-5 should leave the existing 13 AD-459 tests green; Section 6 introduces the new 12 tests. After all sections:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected delta: **+12 to +15 net** (target +12). If <+12 or >+15, hard-stop and triage:

- **<+12:** Builder shipped fewer tests than spec. Audit Section 6.
- **>+15:** Builder added boundary tests (acceptable up to +15). Document in build report.
- **Failures in `test_ad459_saucer_separation.py`:** Section 3 broke the AD-459 v1 contract. Hard-stop, revert Section 3, re-read DLog #1 / #2.

## Hard-stop conditions

1. `set_stress_level` signature changed to `async def`. Revert and re-read DLog #1.
2. Any modification of `DreamScheduler.start/stop` or `ProactiveCognitiveLoop.start/stop`. Revert and re-read DLog #12.
3. Adoption of `EmergenceMetricsEngine`, `EmergentLeadershipDetector`, or `RedTeamLead` in finalize. Revert and re-read DLog #13.
4. Default of `auto_pause_enabled` shipped as True. Revert and re-read DLog #7.
5. `register_subsystem` raises on duplicate instead of replacing with WARNING. Revert and re-read DLog #3.
6. Pre-existing AD-459 v1 tests fail. Hard-stop, surface to Captain.
7. Tests need >2 fix-loop iterations to pass. Hard-stop, surface to Captain.
8. Any modification of `runtime.py`. v1 changes are bounded to events.py / config.py / degradation/* / startup/finalize.py. Revert.

## Tracking updates (post-build, pre-commit)

1. **PROGRESS.md** — append `AD-459b v1 CLOSED.` paragraph mirroring the Wave 60 / Wave 59 shape.
2. **docs/development/roadmap.md:4162** — flip `*(Scoped, OSS, Issue #396)*` to `*(complete)*` per AD-695 / AD-647c precedent.
3. **DECISIONS.md** — NOT modified by this AD per Captain memory rule "only when explicitly required by the prompt"; AD-459b is not a cross-AD architectural inflection.
4. **prompts/wave-plan.yaml** — `id: 61` `status:` field set to `done` after archive.
5. **GH issue #396** — closed by Captain post-merge with commit hash.

## Acceptance Criteria

1. Test count delta lands in [+12, +15] inclusive.
2. All 13 existing AD-459 v1 tests pass unchanged.
3. All 12+ new AD-459b tests pass.
4. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) passes with new total in [11316, 11319].
5. `runtime.degradation_manager.register_subsystem`, `unregister_subsystem`, `registered_subsystems` are public methods on the public `runtime.degradation_manager` attribute.
6. `LifecycleAdapter` and `SheddableSubsystem` re-exported from `probos.degradation`.
7. `EventType.SUBSYSTEM_PAUSED` and `EventType.SUBSYSTEM_RESUMED` defined and emitted on real transitions.
8. `auto_pause_enabled` defaults False; finalize wires zero adopters under default config.
9. With `auto_pause_enabled=True`, finalize wires `dream_scheduler` adopter (when `runtime.dream_scheduler is not None`) and `proactive_loop` adopter (when `runtime.proactive_loop is not None`).
10. No modification of `DreamScheduler`, `ProactiveCognitiveLoop`, or `runtime.py`.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
12. Pre-commit deletion sanity check: max ~10 deletions any single file (events.py 0 / config.py 1 / degradation/manager.py 0 / degradation/__init__.py 0 / startup/finalize.py ~5 line replace). Well below the 200-line surprise-deletion threshold.

## Single AD prompt

Builder reads `prompts/ad-459b-active-shedding-v1.md` next. That file is the authoritative spec; this dispatch is the wave-level framing.
