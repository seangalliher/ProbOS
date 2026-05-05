# WAVE 54 DISPATCH — AD-658a v1 Chain Trace Token I/O Split

**Wave id:** 54
**Single AD:** AD-658a
**Closes:** #408
**Baseline test count:** 11220 (Wave 53, commit `6cbb0ac`) → expected **11226** (+6 net)
**HEAD at draft:** post-Wave-53 (`6cbb0ac`, working tree clean, archive `6cbb0ac`)

## Summary

AD-658 (Wave 30) shipped `ChainExecutionTrace` with a single `tokens_used: int` field that conflates prompt-side and completion-side cost. AD-658a closes the deferred follow-up: split prompt vs completion token tracking end-to-end without breaking any existing consumer.

The plumbing is strictly additive:

```
LLMResponse  ───►  SubTaskResult  ───►  ChainExecutionTrace  ───►  chain_traces.{prompt_tokens,completion_tokens}
   (already)        (NEW fields)          (NEW fields)              (NEW columns + ALTER migration)
```

`tokens_used` is preserved as the prompt+completion sum — every existing read site (8 production + 7 test, all verified) continues to work without modification. `LLMResponse.prompt_tokens` / `LLMResponse.completion_tokens` already exist (AD-431, verified at `types.py:246-247`); v1 plumbs them through the two intermediate dataclass boundaries that currently drop the split.

7 sections, 1 new test file (6 tests), 11 distinct edit points (1 in `sub_task.py` for `SubTaskResult` + 1 in `sub_task.py` for the chain emit site + 1 in `chain_trace.py` + 4 in `journal.py` + 5 in sub-task handlers).

`ChainOptimizer` detector that exploits the split, HXI surface, cache-hit token attribution, and `routers/chain_traces.py` aggregation parameters are explicitly deferred (DLogs #2 / #8 / #9).

## Architect calls (Decision Log)

- **DLog #1 — Strictly additive; `tokens_used` preserved as the sum.** No deprecation, no consumer breakage. 8 production + 7 test read sites of `tokens_used` continue to function unchanged. Wave-10 reframe rule (defer when ≥6 consumer call sites would break) does NOT trigger because no consumer is being modified or removed — only producers gain new fields.

- **DLog #2 — Producer-side full plumbing in v1.** Five `SubTaskResult` construction sites + one `ChainExecutionTrace` site + one INSERT site (in journal) is below the Wave-10 entanglement threshold. Consumer-side detection logic (e.g. ChainOptimizer rule over `prompt_tokens` p95) is AD-658a-2 with a forcing function: ship v1, Captain validates split-field accuracy, then a detector becomes specifiable.

- **DLog #3 — Frozen-dataclass field append (defaulted-after-non-defaulted preserved).** `SubTaskResult` appends after `tier_used` (last field). `ChainExecutionTrace` appends `prompt_tokens` / `completion_tokens` immediately after `tokens_used` for proximity. All defaulted to `0`. Existing call sites use kwargs throughout (verified zero positional `SubTaskResult(...)` constructions beyond `sub_task_type` / `name`).

- **DLog #4 — Defensive `getattr` style preserved across handlers.** `analyze.py` and `compose.py` use bare `response.tokens_used` (LLM response is guaranteed at that branch); `evaluate.py` and `reflect.py` use `getattr(response, "tokens_used", 0)` for stub-tolerance. New `prompt_tokens=` / `completion_tokens=` lines mirror the EXACT style of the `tokens_used=` line directly above them — same handler, same style.

- **DLog #5 — Idempotent ALTER TABLE migration via `_MIGRATIONS_CHAIN_TRACES_AD658A` tuple.** Pattern lifted verbatim from AD-660b at `journal.py:111-114`. Two `ALTER TABLE chain_traces ADD COLUMN ...` statements wrapped in a `try / except Exception: pass` loop in `journal.start()`. Matches the broad-net pattern already in the file (line 211-212).

- **DLog #6 — `journal.record_chain_trace` uses `getattr(trace, "prompt_tokens", 0)`.** Defensive against external fixtures that build raw stubs of `ChainExecutionTrace` predating the field add. Matches the fire-and-forget contract of the journal write path.

- **DLog #7 — `get_recent_chain_traces` is unchanged.** `SELECT *` + `dict(row)` projection automatically picks up the new columns. Same is true of `routers/chain_traces.py:33-37` — Captain-facing API exposes the split with zero router edits.

- **DLog #8 — Cache-hit token attribution deferred (AD-658a-1).** `LLMClient` cache restore at `llm_client.py:464,629` only restores `tokens_used=cached.tokens_used`; the split fields are not cached. Cached chain steps will record `prompt_tokens=0, completion_tokens=0, tokens_used=N`. v1 accepts this — split is "best effort over fresh LLM responses". Forcing function: ship v1; Captain reviews signal-to-noise on a corpus that includes cache hits; AD-658a-1 extends `LLMResponse` cache serialization.

- **DLog #9 — No structured `BaseEvent` subclass. No new EventType. No new pool / agent / module.** The split is plumbing data, not a runtime event. No Pydantic config flag — token split is unconditional (overhead estimate <0.1% per chain step: two integer columns + two integer fields on an already-constructed frozen dataclass).

- **DLog #10 — Column count audit is the principal Section 4 failure mode.** Old INSERT statement = 24 columns + 24 placeholders. New INSERT = 26 columns + 26 placeholders. SEARCH/REPLACE block in Section 4 is sized to lock the entire INSERT body for unique-match — if Builder lands the column-list update without the corresponding placeholder + value-tuple update (or vice versa), `INSERT OR IGNORE` silently fails or `sqlite3.ProgrammingError: Incorrect number of bindings` raises (caught by `record_chain_trace`'s except clause and logged at debug). Pre-build inspection: `rg -n "VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)" src/probos/cognitive/journal.py` — expected 1 hit before; 0 hits after Section 4 lands; 1 hit on the new 26-`?` line confirms the rebind succeeded.

- **DLog #11 — Phantom-API pre-check could not be auto-run.** Same recurring blocker as Waves 52 & 53 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error (terminator missing on line 342). Manual verify-first pass performed at draft — see prompt's "Verified Against Codebase" table (24 verifying greps + line numbers + verifying lines, all confirmed against HEAD `6cbb0ac`). Net-new symbols (7 listed) are intra-prompt-introduction (Section 1 / Section 2 / Section 3a / Section 3b SEARCH/REPLACE). Same FP class as Waves 27-53. Forcing function for tooling-hygiene-AD remains noted but NOT scoped into this wave.

- **DLog #12 — Test count target +6, ceiling +7.** 6 explicit new tests in Section 7. The +7 ceiling allows one boundary discovery during build (precedent: Waves 30, 39, 41, 42, 53 all over-shipped by 1+ via fixture splits). If post-build delta is <+6 or >+7, hard-stop and triage before commit.

## Highest-risk constraints (re-read before each Section)

1. **Section 4 column-count audit (DLog #10).** Old INSERT = 24 columns / 24 placeholders. New INSERT = 26 columns / 26 placeholders. SEARCH locks the whole INSERT body for unique-match. If column list and placeholder count diverge after the edit, `INSERT OR IGNORE` either binds wrong columns or raises `sqlite3.ProgrammingError`. Verify-after pattern: `rg -c "VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)" src/probos/cognitive/journal.py` should return `1` after Section 4 lands.

2. **Section 1 frozen-dataclass field positioning.** `SubTaskResult` already has the constraint that defaulted fields come after non-defaulted. The new `prompt_tokens` / `completion_tokens` (both defaulted to `0`) MUST go after `tier_used` (last field) — not interleaved. Section 1 SEARCH locks the whole class body so the REPLACE is unambiguous.

3. **Section 2 frozen-dataclass field positioning.** `ChainExecutionTrace` insertion target is immediately after `tokens_used` and before `success`. SEARCH locks the wall-clock + execution sub-block (lines ~33-38) for unique-match.

4. **Section 3c migration loop placement.** New AD-658a migration loop MUST run AFTER `_SCHEMA_CHAIN_TRACES` `executescript` (so that fresh DBs already have the columns and the ALTER becomes a no-op via the try/except) and BEFORE the new `_SCHEMA_OPTIMIZATION_PROPOSALS` block (which is unrelated). Section 3c SEARCH anchors on the AD-660b migration loop's closing `pass` plus the AD-659b `executescript` line — unique-match across the file.

5. **Section 5 chain harness emit insertion.** New `prompt_tokens` / `completion_tokens` keyword args are inserted between `tokens_used=result.tokens_used,` and `success=result.success,`. SEARCH locks the entire `ChainExecutionTrace(...)` constructor block so REPLACE is unambiguous.

6. **Section 6 NOTE FOR BUILDER fallbacks.** Sections 6c and 6e include explicit fallback instructions if the literal SEARCH block has drifted. Builder must NOT improvise — fall back to the documented pattern (find the unique block in the same handler that uses `tokens_used=...`, add the two new lines directly under it). Hard-stop only if the entire success-path return cannot be located in the file.

7. **Test 6 (executor emission) signature drift.** Section 7 `test_executor_chain_trace_emission_forwards_token_split` invokes `SubTaskExecutor.execute_chain(chain=..., context=..., journal=...)`. If that signature has drifted since AD-632a, the existing `tests/test_ad658_chain_harness_metrics.py` helper at `_make_executor_with_handler` (line 156+) is the authoritative pattern — adapt the call shape; the assertion (`rows[0]["prompt_tokens"] == 140`) is the contract.

8. **Do NOT touch `LLMResponse`** (`types.py:240-249`) — already has the fields from AD-431. Editing it expands scope and breaks AD-431 contract callers.

9. **Do NOT touch `LLMClient.complete()` cache restore** (`llm_client.py:464,629`). Cache-hit token split is AD-658a-1.

10. **Do NOT touch `routers/chain_traces.py`** — `SELECT *` round-trip exposes the new columns automatically. Adding query parameters is AD-658a-3.

11. **Do NOT touch `chain_optimizer.py`, `diagnostic_context.py`, `clinical_telemetry.py`, `optimization_counselor.py`, `cognitive_agent.py`, or `builder.py`.** All read only `tokens_used`. New detectors / aggregations are AD-658a-2.

12. **Do NOT add a new EventType, Pydantic config, pool, agent, or module.**

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #11, recurring from Waves 52 & 53). Manual verify-first pass: 24 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `6cbb0ac`. Net-new symbols (7 listed in DLog #11) are intra-prompt-introduction (Sections 1 / 2 / 3a / 3b / 4 SEARCH/REPLACE). Same FP class as Waves 27-53.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11220 passed**.

## Build groups

Single group, sequential:

1. Section 1 — `sub_task.py` `SubTaskResult` adds `prompt_tokens` / `completion_tokens`
2. Section 2 — `chain_trace.py` `ChainExecutionTrace` adds `prompt_tokens` / `completion_tokens`
3. Section 3a — `journal.py` `_SCHEMA_CHAIN_TRACES` adds 2 columns
4. Section 3b — `journal.py` `_MIGRATIONS_CHAIN_TRACES_AD658A` tuple
5. Section 3c — `journal.py` `start()` runs the new migration loop
6. Section 4 — `journal.py` `record_chain_trace` INSERT binds 26 columns
7. Section 5 — `sub_task.py` chain harness emit forwards split (defensive `getattr`)
8. Section 6a/6b — `sub_tasks/analyze.py` parse-fail + success populate split
9. Section 6c — `sub_tasks/compose.py` success populates split
10. Section 6d/6e — `sub_tasks/evaluate.py` parse-fail-pass-by-default + success populate split
11. Section 6f — `sub_tasks/reflect.py` success populates split
12. Section 7 — new `tests/test_ad658a_chain_trace_token_split.py` (6 tests)
13. Run focused gate: `pytest tests/test_ad658a_chain_trace_token_split.py tests/test_ad658_chain_harness_metrics.py tests/test_ad632a_sub_task_foundation.py tests/test_ad632c_analyze_handler.py tests/test_ad632d_compose_handler.py tests/test_ad632e_evaluate_reflect.py -v -n 0`
14. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `test_ad658_chain_harness_metrics.py`, `test_ad632a_sub_task_foundation.py`, `test_ad632c_analyze_handler.py`, `test_ad632d_compose_handler.py`, `test_ad632e_evaluate_reflect.py`, or `test_ad659*` regresses after Sections 1/2/4/5/6 land. The change is strictly additive with all new fields defaulted to `0`; existing tests instantiate `SubTaskResult` / `ChainExecutionTrace` with kwargs and never pass positional args beyond `sub_task_type` / `name`. If a regression appears, the SEARCH/REPLACE landed wrong (most likely: column-count drift in Section 4, see DLog #10 verify-after pattern).

- Section 4 column-count audit fails post-edit (`rg` returns ≠ 1 hit on the 26-placeholder INSERT). Hard-stop and re-run the SEARCH/REPLACE — likely the column list and placeholder list diverged.

- Section 3 migration ordering wrong: if the new AD-658a migration tuple runs BEFORE `_SCHEMA_CHAIN_TRACES` execscript, fresh DBs would attempt ALTER on a non-existent table → `OperationalError: no such table: chain_traces` (caught by the try/except, but the column add would silently no-op on fresh DBs — fresh DBs would still get the columns via the schema CREATE, so this is recoverable but indicates Section 3c landed wrong). Pre-build expected ordering at `journal.py:205-220`: (1) `_SCHEMA_CHAIN_TRACES` execscript (CREATE includes new columns) → (2) `_SCHEMA_CAUSAL_TEMPLATES` execscript → (3) AD-660b migration loop → (4) **NEW** AD-658a migration loop → (5) `_SCHEMA_OPTIMIZATION_PROPOSALS` execscript → (6) `_SCHEMA_OPTIMIZATION_DECISIONS` execscript → (7) commit.

- Section 7 test 4 (`test_journal_warm_boot_adds_split_columns_for_pre_ad658a_db`) fails: most likely cause is the test's pre-AD-658a CREATE statement diverging from the actual AD-658 shape (e.g. different `PRIMARY KEY` clause). The test reproduces the AD-658 schema verbatim from `journal.py:56-89` minus the two new columns; if the schema has drifted post-AD-658, copy the current schema from HEAD and remove the two new columns explicitly.

- Section 7 test 6 (`test_executor_chain_trace_emission_forwards_token_split`) fails on `SubTaskExecutor.execute` signature drift. The test mirrors `tests/test_ad658_chain_harness_metrics.py:165+` verbatim (`executor.register_handler` + `executor.execute(chain, observation, agent_id=..., agent_type=..., intent=..., intent_id=..., journal=journal)`). If that signature has drifted further at HEAD, copy the call shape from that file's `test_executor_emits_trace_per_step_with_modulation_snapshot`; the assertion (`trace.prompt_tokens == 140`) is the contract.

- `aiosqlite` import in test fixture fails — Section 7 tests 4 and 5 import `aiosqlite` directly for the warm-boot migration verification (PRAGMA table_info readback). If `aiosqlite` is not installed in the test venv, hard-stop (it's a runtime dep — `pyproject.toml` ships it). Pre-build verify: `d:/ProbOS/.venv/Scripts/python.exe -c "import aiosqlite; print(aiosqlite.__version__)"` — expected non-empty version string.

- Phantom-API pre-check script remains broken (DLog #11) — non-blocker for THIS wave; cleanup AD remains pending.

- Test count delta < +6 OR > +7 — investigate before commit (drift signal).

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage: re-run failing file at `-n 0` per `.github/copilot-instructions.md`. If parallel-only, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-658a CLOSED entry.
- `docs/development/roadmap.md` — add AD-658a as v1 entry under the AD-658 cluster; flip status to ✅ shipped; add AD-658a-1 / AD-658a-2 / AD-658a-3 deferral entries with explicit forcing functions.
- `DECISIONS.md` — prepend AD-658a entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#408** (expect EMU 403 same as Waves 31-53; Captain closes manually).

## Commit message

`AD-658a: Chain trace token I/O split (prompt + completion) (+6 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #11, recurring from Waves 52 & 53). Builder cannot run the standard pre-check; manual verify-first pass already done at draft (24 verifying greps). Forcing function for a tooling-hygiene-AD logged but NOT scoped into this wave.

2. **Section 4 column-count audit is the single highest-risk edit** (DLog #10). Verify-after pattern: `rg -c "VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)" src/probos/cognitive/journal.py` must return `1`. Pre-build same command should return `0` (placeholder count is currently 24, not 26).

3. **Test count baseline asserted at 11220.** Wave-53 dispatch projected exactly 11208 + 12 = 11220; user-confirmed actual baseline post-Wave-53 is 11220 (commit `6cbb0ac`). If pre-flight returns ≠ 11220, hard-stop and triage before dispatching Builder.

4. **Wave 54 is single-AD, sequential, 7 sections + 11 distinct edit points across 7 files + 1 new test file (~210 lines, 6 tests).** Smaller scope than Waves 52 & 53 (which each touched 8-10 sections + new ~460-line module file). Builder envelope: tighter than recent waves.

5. **Strictly additive — zero consumer modifications.** All 8 production read sites of `tokens_used` (chain_optimizer detectors, diagnostic_context, clinical_telemetry, optimization_counselor, routers/chain_traces.py, builder.py, cognitive_agent.py at line 1660, sub_task.py at line 322) and all 7 test read sites continue to function unchanged. The migration is forward-compatible (warm-boot DBs gain columns via idempotent ALTER) and backward-compatible (pre-AD-658a `ChainExecutionTrace` instances accepted via defensive `getattr` in `record_chain_trace`).

6. **No mid-wave reframe expected.** All known scope-bloat targets — `ChainOptimizer` detector for completion-token regressions, HXI surface, `routers/chain_traces.py` aggregation parameters, `LLMClient` cache-restore split — are pre-deferred at the prompt level (DLogs #2, #8, #9 + "Out of scope" section). AD-658a-1 / AD-658a-2 / AD-658a-3 are the explicit forcing functions documented in the prompt body.

7. **No commercial leak.** AD-658a is OSS plumbing: split tokens for visibility into prompt-side vs completion-side cost. Commercial overlays for fleet-wide token cost dashboards / per-tenant cost attribution / RBAC over chain trace columns belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning.
