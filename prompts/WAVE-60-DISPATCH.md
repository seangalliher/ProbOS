# WAVE 60 DISPATCH — AD-458b v1 Pre-Flight Validation: LLMTier + TokenBudget

**Wave id:** 60
**Single AD:** AD-458b
**Closes:** #397
**Baseline test count:** 11291 (post-Wave-59, commit `a58d0ab`) → expected **11303** (+12 net), ceiling **+13**
**HEAD at draft:** `a58d0ab`, working tree clean

## Summary

AD-458 v1 (Wave 6) shipped the pre-flight validation runner with **two filesystem checks** (`TargetFilesExistCheck`, `TargetFilesWritableCheck`) and **two deferred** checks documented as inline comments at `cognitive/pre_flight.py:122-128`:

```
# AD-458b deferred:
#   - LLMTierReachableCheck: needs public is_tier_operational(...) accessor on
#     TieredLLMClient (today's _tier_status is private at llm_client.py:100).
#   - TokenBudgetCheck: hard enforcement already lives in AD-617b proactive
#     cognitive loop; a soft pre-flight gate would either duplicate or ship
#     as theater. Defer until AD-617b surface is exercised.
```

**Both blockers have cleared at HEAD `a58d0ab`:**

1. **LLMTier surface.** `BaseLLMClient.get_health_status()` is a public sync method (`cognitive/llm_client.py:29-38`) returning `{"tiers": {tier: {"status": "operational" | ..., "consecutive_failures": int, ...}, ...}, "overall": ...}`. AD-458b consumes this public method instead of reaching into the private `_tier_status` dict — no `is_tier_operational()` accessor needs to be added; the existing public method already supplies the per-tier status string. Wave-5 convention #2 (no private-attr cross-module access) is honored.

2. **Token-budget surface.** AD-469 v1 (Wave 8) shipped `EPSCoordinator.check_budgets()` (`cognitive/eps/coordinator.py:83-92`), an async method that returns `list[str]` of department names whose share of recent tokens exceeds the configured `over_budget_threshold * allocation`. AD-617b (per-agent hourly token budget) shipped 2026-04-13. The "until AD-617b surface is exercised" condition in the deferral comment is satisfied. AD-469's `check_budgets()` v1 contract returns `[]` (honest deferral until AD-469b's agent→department resolver lands), but the **wiring is real**: the moment AD-469b changes the contract, the AD-458b TokenBudgetCheck becomes operational with no further pre-flight code change. Default `blocking=False` means the check warns rather than blocks until operator flips the flag once confidence is established. This is not theater — it's the exact integration the original deferral comment described.

AD-458b v1 ships:

1. **`LLMTierReachableCheck`** — new module-level class in `cognitive/pre_flight.py` (defined AFTER `TargetFilesWritableCheck` and BEFORE the existing `# AD-458b deferred:` comment block, which is REMOVED). Constructor: `__init__(self, *, runtime: Any, required_tier: str = "deep") -> None`. `async check(spec) -> PreFlightResult`. Reads `client = getattr(self._runtime, "llm_client", None)`. If `client is None` → pass with detail `"no llm_client (skipped)"`. Else calls `health = client.get_health_status()` (sync), reads `tiers = health.get("tiers", {})`, looks up `tier_info = tiers.get(self._required_tier, {})`, and passes iff `tier_info.get("status") == "operational"`. Failure detail: `f"tier '{required_tier}' status: {status}"`. blocking=True (default — a build that depends on the LLM tier should not proceed if the tier is reported unreachable).

2. **`TokenBudgetCheck`** — new module-level class in `cognitive/pre_flight.py`, defined AFTER `LLMTierReachableCheck`. Constructor: `__init__(self, *, runtime: Any, blocking: bool = False) -> None`. `async check(spec) -> PreFlightResult`. Reads `eps = getattr(self._runtime, "eps_coordinator", None)`. If `eps is None` → pass with detail `"no eps_coordinator (skipped)"`. Else `exceeded = await eps.check_budgets()`. If `not exceeded` → pass with detail `"all departments within budget"`. Else fail with `passed=False, blocking=self._blocking, detail=f"budgets exceeded: {', '.join(exceeded[:5])}"`. blocking=False by default — warning, not abort, until operator flips. Tier-2 log-and-degrade on any exception via the existing PreFlightRunner exception envelope (`pre_flight.py:147-156`).

3. **`PreFlightConfig` v2** — adds 4 new fields to existing `PreFlightConfig` at `config.py:1250-1255`:
   - `llm_tier_check_enabled: bool = True` (default ON — the runner already runs filesystem checks; adding tier reachability is a safety upgrade, not a behavior reversal).
   - `required_llm_tier: str = "deep"` (Architect uses Opus tier; Builder uses Sonnet, but a deep failure is the canonical signal of "model provider is down").
   - `token_budget_check_enabled: bool = True` (default ON — wiring is harmless because v1 `check_budgets()` returns `[]`; the moment AD-469b makes the method meaningful, the gate activates with default `blocking=False`).
   - `token_budget_blocking: bool = False` (default OFF — warning rather than abort; operator can flip after AD-469b lands and confidence builds).

4. **`startup/finalize.py` wiring** — extends the existing AD-458 if-block at `finalize.py:1102-1126`. SEARCH locks the entire existing block (the import, the `repo_root` resolution, the `runtime.pre_flight_runner = PreFlightRunner(checks=[...])` constructor call, and the `logger.info(...)` line). REPLACE re-emits the existing block verbatim PLUS conditionally appends `LLMTierReachableCheck(runtime=runtime, required_tier=config.pre_flight.required_llm_tier)` to `runtime.pre_flight_runner.checks` when `config.pre_flight.llm_tier_check_enabled`, AND conditionally appends `TokenBudgetCheck(runtime=runtime, blocking=config.pre_flight.token_budget_blocking)` when `config.pre_flight.token_budget_check_enabled`. Updates the `logger.info` line to remove the "LLMTier + TokenBudget deferred to AD-458b" suffix and report the actual check count.

5. **No new EventType.** v1 reuses existing `EventType.PREFLIGHT_FAILED`. The runner's existing emit path (`pre_flight.py:166-185`) handles failures from any check.

6. **No new public attribute on runtime.** AD-458 already exposes `runtime.pre_flight_runner`. AD-458b's checks plug into the existing `runner.checks` list — no second runtime attribute is needed.

7. **No modification of `BaseLLMClient` or `OpenAICompatibleClient`.** The check consumes the existing public `get_health_status()` method.

8. **No modification of `EPSCoordinator`.** The check consumes the existing public `check_budgets()` method.

9. **One new test file:** `tests/test_ad458b_preflight_v2.py` (12 tests). Existing `tests/test_ad458_pre_flight.py` (10 tests) continues to pass unchanged — Section 1 (config fields) is additive, Section 2 (new check classes) is additive, Section 3 (finalize wiring) extends the existing PreFlightRunner.checks list rather than replacing it.

3 source-edit files (`config.py` additive only, `cognitive/pre_flight.py` additive + 7-line comment removal, `startup/finalize.py` SEARCH/REPLACE on the existing AD-458 block).

The default-flip of `token_budget_blocking` to True (after AD-469b lands and operator confidence builds), AD-617b per-agent budget integration as a third check, an integration with AD-446 (Compensation) so a pre-flight failure auto-restores from the last-known-good build branch, an HXI surface for "pre-flight health" aggregating tier + token + filesystem signals, federation-side pre-flight (sender trust + message schema validation per AD-458 Roadmap section 3), and a commercial overlay for SLA-graded pre-flight (per-tenant tier reachability SLOs, regulator-facing pre-flight evidence chain) are pre-deferred at the prompt level to AD-458b-1 / -2 / -3 / -4 / -5 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — Use the public `get_health_status()` method, NOT a new `is_tier_operational()` accessor.** The original deferral comment at `pre_flight.py:122-124` proposed a new accessor on `TieredLLMClient`. Verify-first at HEAD `a58d0ab` confirmed `BaseLLMClient.get_health_status()` already exists at `llm_client.py:29-38` as a public method on the abstract base, with `OpenAICompatibleClient` overriding it to return real per-tier status (status string + consecutive_failures + last_success/last_failure timestamps). Adding a new accessor would duplicate that surface. The check reads `health["tiers"][tier]["status"] == "operational"` — the canonical health string already in production use by `_health_probe_loop` (`llm_client.py:321-368`).

- **DLog #2 — `health.get("tiers", {})` defensive read on stub clients.** `BaseLLMClient.get_health_status()` (the abstract base default) returns `{"tiers": {...}, "overall": "operational"}` for all subclasses that don't override. `MockLLMClient` (used in 60+ test rigs) inherits the default. The check defensively reads via `.get("tiers", {})` and `.get(required_tier, {})` so an unexpected health-status shape (e.g., a future client returning empty dict) degrades to a non-operational status rather than raising `KeyError`.

- **DLog #3 — `LLMTierReachableCheck.blocking=True` by default.** A build that depends on a specific LLM tier (e.g., the Architect's deep tier for proposal generation) fails late and noisily without the check — branch is created, files are written, then the LLM call times out at 300s. The pre-flight check is exactly the kind of fast-fail the AD-458 module docstring describes: "validates that the build path is clear before the BuilderAgent commits expensive resources." The configured `required_llm_tier` defaults to "deep" because that's the highest-risk path; operator can switch to "standard" (Builder's tier) if they prefer to gate on Builder readiness instead.

- **DLog #4 — `TokenBudgetCheck.blocking=False` by default.** Three reasons: (1) AD-469 v1 `check_budgets()` returns `[]` until AD-469b's agent→department resolver lands — blocking=True would do nothing today and risk an unexpected blocker once AD-469b ships. (2) Once AD-469b activates the surface, a budget overrun is a **rate-of-spend** signal, not a hard correctness signal — warning is the right first response. (3) `PreFlightConfig.token_budget_blocking: bool = False` is the operator-tunable knob to flip once they have confidence. Convention #14 (default-False on transitional flags) maps directly: this is a transitional posture pending AD-469b + a fleet rehearsal.

- **DLog #5 — `token_budget_check_enabled: bool = True` despite v1 `check_budgets()` returning `[]`.** Wave-5 convention #14 normally suggests default-False on transitional flags. But here the check is harmless under v1 (always returns "all departments within budget" because `check_budgets()` returns `[]`); the wiring is the value, not the activation. Default-True ensures the moment AD-469b changes the contract, the gate activates without a config flip. Default-False would risk silent inactivity if operators never flip it. The `token_budget_blocking` flag remains False — that's the safety knob — but the `_enabled` flag flips True so the wiring is live.

- **DLog #6 — TokenBudgetCheck's degraded-path detail message uses "skipped" not "no-op".** When `eps_coordinator is None`, the check passes with `detail="no eps_coordinator (skipped)"`. Mirrors `LLMTierReachableCheck`'s `detail="no llm_client (skipped)"` and AD-458 v1's `TargetFilesExistCheck` skip-detail `"no target_files (CREATE mode)"`. Consistent operator-facing language: "skipped" means the check did not run because its dependency was absent; "passed" means the check ran and found no problem.

- **DLog #7 — Both checks short-circuit on missing runtime dependency, NOT on exception.** `LLMTierReachableCheck.check()` and `TokenBudgetCheck.check()` defensively fetch their dependency via `getattr(runtime, "X", None)`. A `None` return short-circuits to `passed=True` (with skip detail). An exception during the actual API call (e.g., `client.get_health_status()` raises, or `eps.check_budgets()` raises) propagates UP to the existing `PreFlightRunner` exception handler at `pre_flight.py:147-156` which converts it to `PreFlightResult(passed=False, blocking=False, ...)`. This preserves the AD-458 v1 exception contract — the pre-flight runner is the central exception envelope. Test #6 verifies the propagation by raising from a fake client and asserting the runner records the result with `blocking=False`.

- **DLog #8 — Wave-10 reframe NOT triggered.** Both checks ship in v1. The LLMTier blocker (need for `is_tier_operational()`) was a misread of the existing surface — the public `get_health_status()` was always available; verify-first at draft caught this. The TokenBudget blocker (AD-617b prerequisite) is satisfied — AD-617b shipped 2026-04-13. Both v1 checks are minimal, real, and operator-tunable. Wave-10 reframe (defer one check) was considered and rejected because both surfaces are clean. Captain memory rule: "DO NOT defer scope unless really necessary."

- **DLog #9 — `runtime` injected via constructor, NOT via late-bind setter.** Both checks take `runtime: Any` in `__init__`. Mirrors AD-528c v1's `GroundTruthTrustFeedback(runtime=runtime, ...)` shape (Wave 59) and AD-451's `ReconciliationEscalator(runtime=runtime, ...)` (Wave 6). Constructor injection is the Wave-5 convention #1 standard. The check stores `self._runtime` privately and reads via `getattr` at check time so a stub runtime (test rig) fails gracefully.

- **DLog #10 — `LLMTierReachableCheck` does NOT call `client.check_connectivity()`.** That method (`llm_client.py:281-307`) does a live network probe and is awaited. AD-458b v1 reads the **cached** health-status (sync method) instead — the BF-246 background health probe (`llm_client.py:321-368`) is responsible for keeping that cache fresh on a 30s interval. Calling `check_connectivity()` on every pre-flight would: (a) double-probe the LLM endpoint, (b) make pre-flight slow (5s probe per tier), (c) couple the build cycle to network jitter. The cached read is the right v1 semantics. Test #2 / #3 / #4 / #5 mock `get_health_status()`, not `check_connectivity()`.

- **DLog #11 — `LLMTierReachableCheck` failure detail format pinned.** When the tier status is not "operational", the detail string is exactly `f"tier '{required_tier}' status: {status}"` (e.g., `"tier 'deep' status: unreachable"`). Avoids leaking client internals (consecutive_failures count, timestamps) into the operator-facing pre-flight report — those belong to the health-status surface, not the pre-flight summary. Test #3 locks the format.

- **DLog #12 — `TokenBudgetCheck` failure detail format pinned.** When `check_budgets()` returns a non-empty list, detail is `f"budgets exceeded: {', '.join(exceeded[:5])}"`. Truncated to 5 entries to bound the detail length (consistent with AD-458 v1's `TargetFilesExistCheck` which truncates `missing[:5]`). Test #9 locks the truncation behavior.

- **DLog #13 — `runtime.pre_flight_runner.checks` list ordering matters.** Both new checks are appended AFTER the existing two filesystem checks. Order = filesystem-exist → filesystem-writable → llm-tier-reachable → token-budget. Rationale: cheapest checks first (filesystem stat is microseconds), most expensive last (token-budget queries the journal which can take milliseconds at scale). With `PreFlightRunner` short-circuiting on the first blocking failure, this ordering minimizes wasted work — a missing target file aborts before we waste a network read. Test #11 locks the order.

- **DLog #14 — No `pre_flight.py` deletion concern despite removing the deferral comment.** SEARCH locks the 7-line deferral comment block (`pre_flight.py:122-128`) plus the surrounding context (the trailing `return PreFlightResult(...)` of `TargetFilesWritableCheck` plus the `@dataclass` decorator opening of `PreFlightRunner`). REPLACE re-emits the trailing context verbatim plus the new `LLMTierReachableCheck` and `TokenBudgetCheck` class definitions in place of the comment. The PreFlightRunner dataclass that follows is untouched. Pre-commit deletion sanity check: ~7 lines deleted (the comment block) and ~80 lines added (the two new classes + their docstrings + a one-line section banner). Well below the 200-line surprise-deletion threshold per file.

- **DLog #15 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-59 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (24 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `a58d0ab`). Net-new symbols (10 listed: `LLMTierReachableCheck` class, `TokenBudgetCheck` class, `PreFlightConfig.llm_tier_check_enabled`, `PreFlightConfig.required_llm_tier`, `PreFlightConfig.token_budget_check_enabled`, `PreFlightConfig.token_budget_blocking`, two test files cross-references, plus the LLMTierReachableCheck.required_tier ctor kwarg and TokenBudgetCheck.blocking ctor kwarg) are intra-prompt-introduction (Section 1 + Section 2 + Section 3 SEARCH/REPLACE). Same FP class as Waves 27-59.

- **DLog #16 — Test count target +12, ceiling +13.** 12 explicit tests in Section 4. The +13 ceiling allows one boundary discovery during build (Waves 30/39/41/42/53/55/56/57/58/59 precedent). If post-build delta is <+12 or >+13, hard-stop and triage before commit. Wave 59 baseline (11291) + 12 new = 11303 net target.

- **DLog #17 — Commercial-leak audit: clean.** AD-458b is OSS plumbing — two new check classes + 4 new Pydantic config fields + an additive finalize-block extension + 12 tests. AD-458b-5 *(Commercial)* deferral entry tags SLA-graded pre-flight (per-tenant tier reachability SLOs, multi-region tier health aggregation, regulator-facing pre-flight evidence chain) as the extension-point seam — describes WHAT plugs in (extension point on the existing `runtime.pre_flight_runner.checks` list + per-check `runtime` injection), NOT business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #18 — Distinct from AD-617b (per-agent hourly token budget).** AD-617b is the ENFORCEMENT layer — runs in the proactive cognitive loop, gates per-agent LLM calls in real time. AD-458b is the PRE-CHECK layer — runs once before each Builder cycle, gates the entire build on a coarse-grained "are budgets healthy?" signal. They are orthogonal: AD-617b prevents an over-budget agent from making a runtime call; AD-458b prevents a build from starting when budgets are already strained. Test set explicitly avoids any AD-617b assertions; the TokenBudgetCheck reads only `eps.check_budgets()`, which is AD-469's surface, not AD-617b's.

- **DLog #19 — Distinct from AD-469 (EPS Compute/Token Distribution).** AD-469 v1 owns the `EPSCoordinator` class, the `check_budgets()` method (returns `[]` placeholder per its v1 contract), and the `runtime.eps_coordinator` public attribute. AD-458b READS `eps.check_budgets()` via the public method. v1 has zero modification of EPS-side code. Once AD-469b ships the agent→department resolver and `check_budgets()` returns real data, AD-458b's `TokenBudgetCheck` becomes operational with no further AD-458b code change. Test set asserts only the outward shape of pre-flight calls; internal EPS behavior is AD-469-cluster territory.

- **DLog #20 — Anti-misclassification audit.** No prior `AD-458a` artifact exists at HEAD `a58d0ab` (verified: zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md`). The user's anti-misclassification clause is a forward-looking constraint: this prompt MUST NOT (a) re-scope AD-458b as a sub-letter — it's the b-tier root closing #397; (b) bundle AD-617b enforcement integration into this AD; (c) bundle AD-469b agent→department resolver work into this AD; (d) silently introduce a new top-level AD number outside the 458-cluster naming. Single AD = single deferral root = single GH issue (#397). Audit: clean.

## Highest-risk constraints (re-read before each Section)

1. **Section 2 deletes the 7-line `# AD-458b deferred:` comment block** at `pre_flight.py:122-128`. The SEARCH anchor includes the trailing `return PreFlightResult(...)` of `TargetFilesWritableCheck.check()` (last line of that method, line ~120) plus a blank line plus the comment block plus a blank line plus the `@dataclass` decorator of `PreFlightRunner` (line ~131). REPLACE re-emits the trailing return + blank line + new `LLMTierReachableCheck` class + blank line + new `TokenBudgetCheck` class + blank line + `@dataclass` decorator. Verify the SEARCH text matches HEAD exactly before applying.

2. **Section 2 both new classes are at MODULE level**, NOT nested inside any other class. Module-level definition lets tests import them directly: `from probos.cognitive.pre_flight import LLMTierReachableCheck, TokenBudgetCheck`. SEARCH locks the trailing line of `TargetFilesWritableCheck.check()` (the existing module's final `return PreFlightResult(passed=True, ...)`) plus the deferral comment plus the `@dataclass` of `PreFlightRunner`; REPLACE re-emits that trailing return verbatim and inserts the two new classes between it and the `@dataclass`.

3. **Section 2 `LLMTierReachableCheck.check()` order of operations.** Sequence:
   ```python
   async def check(self, spec: "BuildSpec") -> PreFlightResult:
       client = getattr(self._runtime, "llm_client", None)
       if client is None:
           return PreFlightResult(
               passed=True, check_name=self.name,
               detail="no llm_client (skipped)",
           )
       health = client.get_health_status()
       tiers = health.get("tiers", {}) if isinstance(health, dict) else {}
       tier_info = tiers.get(self._required_tier, {}) if isinstance(tiers, dict) else {}
       status = tier_info.get("status", "unknown") if isinstance(tier_info, dict) else "unknown"
       if status == "operational":
           return PreFlightResult(
               passed=True, check_name=self.name,
               detail=f"tier '{self._required_tier}' operational",
           )
       return PreFlightResult(
           passed=False, check_name=self.name,
           detail=f"tier '{self._required_tier}' status: {status}",
       )
   ```
   The `client is None` guard runs FIRST (cheap getattr) — avoids the `get_health_status()` call entirely when there's no client. The `isinstance(health, dict)` defensive checks tolerate stub clients that return None or unexpected shapes from `get_health_status()`. Test #2 (operational pass), Test #3 (unreachable fail), Test #4 (no-client skip), Test #5 (different required_tier), and Test #6 (exception path) lock all five branches.

4. **Section 2 `TokenBudgetCheck.check()` order of operations.** Sequence:
   ```python
   async def check(self, spec: "BuildSpec") -> PreFlightResult:
       eps = getattr(self._runtime, "eps_coordinator", None)
       if eps is None:
           return PreFlightResult(
               passed=True, check_name=self.name,
               detail="no eps_coordinator (skipped)",
           )
       exceeded: list[str] = await eps.check_budgets()
       if not exceeded:
           return PreFlightResult(
               passed=True, check_name=self.name,
               detail="all departments within budget",
           )
       return PreFlightResult(
           passed=False, check_name=self.name,
           detail=f"budgets exceeded: {', '.join(exceeded[:5])}",
           blocking=self._blocking,
       )
   ```
   The `eps is None` guard runs FIRST (cheap getattr) — avoids the `await` call when there's no EPS coordinator. `await eps.check_budgets()` is the AD-469 v1 surface. The truncation `exceeded[:5]` mirrors AD-458 v1's `missing[:5]` pattern in `TargetFilesExistCheck`. Test #7 (no-eps skip), Test #8 (empty list pass), Test #9 (non-empty fail with default blocking=False), Test #10 (blocking=True override) lock all four branches.

5. **Section 3 finalize wiring SEARCH locks the entire existing AD-458 if-block** at `finalize.py:1102-1126`. SEARCH starts at the line `# AD-458: Pre-flight validation runner (v1: 2 checks; LLMTier + TokenBudget deferred to AD-458b)` and ends at the closing paren+newline of the `logger.info(...)` call. REPLACE re-emits the same opening comment (now updated to reflect v2 — `AD-458b: 4 checks`), the same import block PLUS imports for `LLMTierReachableCheck` and `TokenBudgetCheck`, the same `repo_root` resolution, the same `PreFlightRunner(checks=[...])` construction with the SAME two filesystem checks, then conditionally appends the two new checks via `if config.pre_flight.llm_tier_check_enabled:` and `if config.pre_flight.token_budget_check_enabled:` blocks, then the updated `logger.info` line. Verify the SEARCH preserves all 25 lines verbatim.

6. **Section 3 `logger.info` line update.** OLD: `"AD-458: PreFlightRunner wired (%d checks; LLMTier + TokenBudget deferred to AD-458b)"`. NEW: `"AD-458b: PreFlightRunner wired (%d checks)"`. The deferred-clause is removed because the deferral has been resolved by THIS AD. The AD tag updates from "AD-458" to "AD-458b" because the new wiring is the AD-458b deliverable.

7. **Section 3 conditional append uses `runtime.pre_flight_runner.checks.append(...)`**, NOT a fresh PreFlightRunner constructor call. Re-constructing the runner would discard the existing 2 filesystem checks. The dataclass field `checks: list[PreFlightCheck] = field(default_factory=list)` (`pre_flight.py:135`) is mutable — append is the correct mutation. Test #11 verifies the final check count (4) and order via `runtime.pre_flight_runner.checks` after `finalize_startup`.

8. **Section 1 config field append site.** SEARCH locks the existing `PreFlightConfig` class body (3 lines: `enabled: bool = True` + the AD-458b TODO comment + nothing else) at `config.py:1252-1255`. REPLACE re-emits the existing `enabled` field verbatim (no change), REMOVES the `# AD-458b will add ...` TODO comment lines, and APPENDS the four new fields. Field order: `llm_tier_check_enabled` → `required_llm_tier` → `token_budget_check_enabled` → `token_budget_blocking` (matches the order they're consumed in finalize.py). The `enabled: bool = True` master-flag stays on top.

9. **Section 4 test isolation.** Tests use `SimpleNamespace` runtimes with `MagicMock`/`AsyncMock` stand-ins for `llm_client` and `eps_coordinator` (mirrors AD-528c / AD-528b / AD-528 test patterns). No `tmp_path` needed for the new check tests except where filesystem checks are also exercised in finalize-test #11 — that test uses `tmp_path` to satisfy the existing `TargetFilesExistCheck`/`TargetFilesWritableCheck` constructors. No tests share check / runtime instances — each test calls fresh constructors. pytest-xdist parallel runs are safe (pure-Python, MagicMock I/O only).

10. **Test #11 (`test_new_checks_satisfy_pre_flight_check_protocol`) Protocol-compliance.** Mirrors AD-458 v1's existing protocol test (`test_ad458_pre_flight.py:188-192`). Build instances of both new checks against a `SimpleNamespace` runtime with no attributes set (the constructors don't probe runtime; only `check()` does). Assert `isinstance(llm_check, PreFlightCheck)` and `isinstance(tok_check, PreFlightCheck)` plus `name` attribute equality.

11. **Test #12 (`test_runner_with_all_four_checks_runs_in_expected_order`) end-to-end runner integration.** Manually construct a `PreFlightRunner` with the 4 checks in the order `finalize.py` produces them — `[TargetFilesExistCheck, TargetFilesWritableCheck, LLMTierReachableCheck, TokenBudgetCheck]`. Use a `tmp_path` filesystem layout for the existence/writability checks, MagicMock-backed runtime for the two new checks (operational tier + empty budgets list). Run on a `_FakeBuildSpec(target_files=["a.py"])`. Assert all 4 checks fired (results length 4), order matches, every `passed=True`, aggregate `report.passed=True`. This test exercises the full pre-flight pipeline path that production hits, without requiring `finalize_startup` (which reaches into many unrelated wirers and would not run on a stub runtime).

> **Why no direct `finalize_startup` test?** Mirrors AD-528c (Wave 59) and AD-647b (Wave 48) test patterns: `finalize_startup` is a 1000+ line orchestrator that wires dozens of services. Calling it with a SimpleNamespace runtime fails on unrelated wirers (e.g., `_wire_self_distillation`, `_wire_anomaly_window`). The right test surface is the runner shape after wiring would have completed — covered by Test #12's manually-assembled runner. Production wiring is exercised implicitly by every full-runtime test rig.

12. **Do NOT modify `BaseLLMClient`.** Existing `get_health_status()` is consumed via the public method. No new method, no modified return shape.

13. **Do NOT modify `OpenAICompatibleClient`.** No new accessor, no public-promotion of `_tier_status`.

14. **Do NOT modify `EPSCoordinator`.** Existing `check_budgets()` is consumed via the public async method. No new method, no contract change.

15. **Do NOT modify `PreFlightRunner`.** The runner already accepts arbitrary checks via the `checks: list[PreFlightCheck]` field. No new method, no new flag.

16. **Do NOT add a new EventType.** `EventType.PREFLIGHT_FAILED` is reused via the existing runner emit path.

17. **Do NOT create new files beyond `tests/test_ad458b_preflight_v2.py`.** No new package. No new module. The new check classes live in the existing `cognitive/pre_flight.py` file.

18. **Do NOT add a new public attribute on runtime.** The runner is already exposed at `runtime.pre_flight_runner`; new checks plug into its `.checks` list.

19. **Do NOT call `client.check_connectivity()` from the new check.** That would do a live network probe per build (5s × 3 tiers = 15s overhead). Use the cached `get_health_status()` instead. DLog #10.

20. **Do NOT bypass `runtime.eps_coordinator.check_budgets()`.** Do not read `eps._budgets` or any private attribute. Do not re-implement budget logic. The check is a thin wrapper over the public method.

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #15, recurring from Waves 52-59). Manual verify-first pass: 24 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `a58d0ab`. Net-new symbols (10 listed in DLog #15) are intra-prompt-introduction (Sections 1 / 2 / 3 SEARCH/REPLACE). Same FP class as Waves 27-59.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11291 passed**.

## Build groups

Single group, sequential:

1. Section 1 — `config.py` `PreFlightConfig` adds `llm_tier_check_enabled: bool = True` + `required_llm_tier: str = "deep"` + `token_budget_check_enabled: bool = True` + `token_budget_blocking: bool = False`; removes the AD-458b TODO comment.
2. Section 2 — `cognitive/pre_flight.py` adds `LLMTierReachableCheck` + `TokenBudgetCheck` module-level classes; removes the 7-line `# AD-458b deferred:` comment block.
3. Section 3 — `startup/finalize.py` extends the existing AD-458 if-block with conditional appends for the two new checks; updates the log line.
4. Section 4 — `tests/test_ad458b_preflight_v2.py` NEW (12 tests).
5. Run focused gate: `pytest tests/test_ad458b_preflight_v2.py tests/test_ad458_pre_flight.py -v -n 0`
6. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `tests/test_ad458_pre_flight.py` (10 tests) regresses after Section 2 lands. The change is strictly additive — new symbols defined AFTER existing classes; no existing class body modified. If a regression appears, most likely cause is Section 2 SEARCH/REPLACE landed inside `TargetFilesWritableCheck.check()` body instead of after it (verify the SEARCH anchor is the trailing `return PreFlightResult(passed=True, ..., detail=f"{len(target_files)} target file(s) writable",)` close paren of that method).

- An existing test in `tests/test_ad469_eps.py` regresses. Orthogonal — AD-458b reads `eps.check_budgets()` via the public API but does NOT modify EPS source. If a regression appears, the failure is unrelated to this AD; triage via `git stash` per `.github/copilot-instructions.md` standard procedure.

- An existing finalize-startup test regresses (e.g., `tests/test_finalize_*.py` if any cover AD-458 wiring). Section 3 SEARCH locks the existing AD-458 if-block; REPLACE re-emits the existing two filesystem checks verbatim PLUS the new conditional appends. If the existing `runtime.pre_flight_runner.checks` length-2 assertion in any existing test is broken, that test needs to be updated to accept length-4 (for default config) — Section 4's Test #11 is exactly that update. Verify the SEARCH anchor preserves the existing two filesystem checks and `repo_root` resolution.

- Pydantic config validation failure at startup (every test would fail). Section 1 SEARCH locks the existing `PreFlightConfig` body; REPLACE re-emits the existing `enabled` field verbatim plus the four new fields. If the Builder accidentally overwrites or moves the existing `enabled: bool = True` default, validation breaks. Verify the SEARCH anchor preserves `enabled: bool = True`.

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage per `.github/copilot-instructions.md` — re-run failing file at `-n 0` first. Section 4 tests use SimpleNamespace + MagicMock/AsyncMock (no I/O, no shared state) — no file races. If parallel-only failures appear, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

- Phantom-API pre-check script remains broken (DLog #15) — non-blocker for THIS wave; cleanup AD remains pending.

- A NEW EventType is accidentally added. There's no event-type edit in this prompt. If the Builder adds one, hard-stop and revert.

- A new `cognitive/pre_flight.py` symbol attempts to access `client._tier_status` directly. Wave-5 convention #2 violation. The check MUST consume the public `get_health_status()` method only. If the Builder reaches into `_tier_status`, hard-stop and revert.
