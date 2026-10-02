# Test Suite Optimization Plan

**Status:** Execution started 2026-09-30. Batch A (#1443) ships P0.2's #1419 G-1/G-1b, P0.3, P0.4, V2 and one V1 fix. Batch B (#1445) ships P0.1 (the test_experience.py split) and the rest of V1. Batch C (#1446) ships P1.3's test-side CodebaseIndex memo. Batch D (#1448) ships P2.6 (overlay hermeticity), the five remaining same-file identical-body pairs (V1), the V4 literal-copy removal, and root-cause fixes for two §3.7 flakes. Batch E ships P1.4 (each worker starts on one of the heaviest files; full LPT was measured and rejected), P1.2 (teardown-scoped shutdown grace, first slice) and P0.5 with a report-only P3.1. P2.2's first slice (the phantom-precheck kwargs tests call the helper in-process) follows it. G-2 is deferred (see P0.2). Everything else below is still a proposal. Evidence snapshot taken 2026-09-30.
**Parent program:** AD-1270f "Fail-Broad Impact Selection and Balanced Full Gate" in the [Platform Maturity Program](platform-maturity-program.md) ([#1324](https://github.com/seangalliher/ProbOS/issues/1324)). The flake root causes in P0.2 are already recorded as G-1/G-2 in [#1419](https://github.com/seangalliher/ProbOS/issues/1419).
**AD allocation:** None. Every item maps to an existing owner. If a production change is picked up and needs its own AD, allocate one with `scripts/ad_ceiling.py` at that point.
**Scope:** The Python suite under `tests/`, run by the canonical gate ([run_test_gate.py](../../scripts/run_test_gate.py)) and by CI. The UI Vitest job is out of scope: it takes 4.9 minutes in CI and isn't the bottleneck.

## 1. Summary

The canonical gate spends **18:10 in pytest (about 19 minutes end to end) for 37,841 tests**. CI's `python-tests` job takes **36.4 minutes** against a 45-minute timeout, up from a 27.1-minute median at the start of September. Three measured causes explain most of that time.

1. **One file sets the gate's wall-clock.** The sample covers 14 green canonical gates since 2026-09-03. In every one, the busiest xdist worker was the one running [test_experience.py](../../tests/test_experience.py), and that file alone took 777–941 s. The second-busiest worker finished 270–370 s earlier. So 15 of the 16 workers sit idle for the last five minutes or more of every gate. More workers can't help, because `--dist=loadfile` never splits a file.
2. **Full `ProbOSRuntime` boots take 60% of all test time.** The 53 files that build and start a runtime account for 5,452 s of the 9,056 s total. A warm boot and stop costs about 7 s, and about 5 s of that is incidental:
   - 3.0 s of fixed shutdown sleeps;
   - about 2 s re-parsing all 963 source files to rebuild the CodebaseIndex.

   An experiment that removed only those two costs cut two boot-heavy subsets by 59–63%, and every test still passed.
3. **Scheduling ignores duration.** xdist orders files by *test count*. A heavy file with few tests, such as `test_experience.py` (109 tests, 872 s), starts late.

Confirmed flakes also cost time: commits that went red and then green with no code change used 2.4 gate-hours in September. The biggest flake class ([#1419](https://github.com/seangalliher/ProbOS/issues/1419) G-1/G-2) caused 48 and 58 cascading failures in two separate runs.

**Projected result.** Every collected test still runs exactly once in every phase.

| After | pytest phase | Source of the saving |
|---|---:|---|
| Phase 0: split `test_experience.py` | about 13.7 min | critical path only |
| Phase 1: duration-ordered scheduling and cheaper runtime boots | about 9.7 min | balance, plus about 27% of suite CPU removed |
| Phase 2: 20-worker sweep, if it scales | at best about 8.3 min | throughput |

Phase 1 brings the whole gate to about 10.4 minutes (pytest plus about 41 s of preflight and wrapper time), under the AD-1270f target of 12:00. Phase 1 alone takes CI from about 36 to about 27 minutes, and three duration-balanced shards take it to about 10–12 minutes.

**Are some tests duplicative or low-value? (§9)** A few, but that isn't where the time goes:

- literal duplicates cost 12.6 s in total;
- there are a handful of tests that can't fail or don't set up what their names claim;
- about 40 slow tests (344 s) start a runtime and then assert little.

Gate history shows the broad suite catches real cross-cutting defects: untouched existing tests led to 11 product fixes in September. The cheap pinning tests that sometimes just need updating are exactly the ones worth running first, not the ones to delete.

## 2. Quality constraints (non-negotiable)

These come from the AD-1270f acceptance criteria and the Testing Standards in `.github/copilot-instructions.md`.

- **Every collected node runs exactly once** in the canonical gate. The target may not be met with a skip, a deselection, a timeout change, or a semantic change. The frozen full gate remains the only release authority.
- **No test is deleted, merged, or scaled down to save time.** For example, the 1000-row capacity proof stays at 1000 rows. A test may still be retired for *value* reasons — a literal duplicate, or a test that can't fail — but only through the V7 protocol (§9.4).
- **Isolation stays per test.** No `ProbOSRuntime` is shared across a module, class, or session.
- **Production defaults don't change.** If the test profile differs from `SystemConfig()` defaults, the difference goes on an explicit allowlist that a test pins (§5.4).
- **Scheduling may change *where* and *when* a test runs, never *whether* it runs.** The wrapper's existing checks (identical collection, exactly-once execution, JUnit/collection equality) remain the authority.

## 3. Evidence

### How the data was collected

- **Gate artifacts:** 131 canonical full gates since 2026-08-31, from `logs/gates/` in every linked worktree. 112 of them include per-worker execution evidence (`*.collection-workers/gw*.json`).
- **Experiments:** run on 2026-09-30 on the reference host:
  - Ryzen 9 7950X3D, 16 cores / 32 threads, 64 GB RAM, Windows;
  - Python 3.12.13, pytest 9.0.2, xdist 3.8.0, pytest-asyncio 1.3.0.
- **Baseline run:** `issue-1131-r2`, commit `a37e39ed`, started 2026-09-30T14:37Z. pytest reported 1,090.5 s, and the gate spent about 41 s outside pytest.

### 3.1 Where the time goes

| Per-test duration | Tests | Share of tests | Time | Share of time |
|---|---:|---:|---:|---:|
| < 10 ms | 24,604 | 65.0% | 66 s | 0.7% |
| 10–100 ms | 7,538 | 19.9% | 272 s | 3.0% |
| 0.1–1 s | 4,660 | 12.3% | 1,388 s | 15.3% |
| 1–5 s | 445 | 1.2% | 888 s | 9.8% |
| 5–30 s | 589 | 1.6% | 6,107 s | 67.4% |
| ≥ 30 s | 5 | < 0.1% | 337 s | 3.7% |

**594 tests (1.6%) take 71% of the time. The 32,142 tests under 100 ms (85% of all tests) take 3.7%.** Pruning or merging fast tests would buy almost nothing.

Time also clusters by file:

- the top 10 files take 37% of the time, and the top 50 take 74%;
- 1,146 of the 1,510 files each total under 1 s.

The heaviest files:

| File | Time | Tests | Mean per test |
|---|---:|---:|---:|
| `test_experience.py` | 872 s | 109 | 8.0 s |
| `test_dag_proposal.py` | 365 s | 42 | 8.7 s |
| `test_system_qa.py` | 362 s | 74 | 4.9 s |
| `test_distribution.py` | 327 s | 107 | 3.1 s |
| `test_runtime.py` | 292 s | 29 | 10.1 s |
| `test_ad1192_owned_steps_store.py` | 275 s | 380 | 0.7 s (one test takes 171 s) |
| `test_knowledge_store.py` | 247 s | 308 | 0.8 s |
| `test_ad1205_fault_paths.py` | 222 s | 231 | 1.0 s |
| `test_ad1194_unified_capability_triage.py` | 208 s | 188 | 1.1 s |
| `test_run_test_gate.py` | 195 s | 83 | 2.4 s |

### 3.2 The critical path

"Busy" is the sum of JUnit times for the nodes a worker actually executed.

| Gate (date) | Tests | pytest wall | Busiest worker | `test_experience.py` on it | 2nd busiest | Mean |
|---|---:|---:|---:|---:|---:|---:|
| 09-03 | 28,469 | 1,030 s | 908 s | 907 s | 537 s | 490 s |
| 09-06 | 28,965 | 974 s | 813 s | 811 s | 471 s | 430 s |
| 09-09 | 29,071 | 1,044 s | 886 s | 883 s | 537 s | 495 s |
| 09-12 | 30,046 | 992 s | 865 s | 859 s | 532 s | 484 s |
| 09-15 | 30,844 | 953 s | 784 s | 777 s | 464 s | 427 s |
| 09-18 | 31,210 | 1,095 s | 948 s | 941 s | 614 s | 574 s |
| 09-20 | 33,459 | 1,100 s | 935 s | 919 s | 592 s | 564 s |
| 09-24 | 35,293 | 1,041 s | 860 s | 832 s | 577 s | 519 s |
| 09-27 (1429) | 36,815 | 978 s | 826 s | 792 s | 553 s | 506 s |
| 09-27 (1431) | 36,975 | 983 s | 829 s | 794 s | 554 s | 509 s |
| 09-27 (1433-r2) | 37,104 | 1,090 s | 906 s | 868 s | 618 s | 565 s |
| 09-28 | 37,233 | 1,081 s | 879 s | 835 s | 598 s | 553 s |
| 09-30 (1083) | 37,653 | 1,131 s | 938 s | 899 s | 644 s | 577 s |
| 09-30 (1131-r2) | 37,841 | 1,095 s | 925 s | 872 s | 621 s | 566 s |

- **The wall-clock stayed flat while the suite grew 33%.** Tests went from 28.5K to 37.8K, but wall time held at 950–1,130 s. The growth landed on idle workers: mean busy time rose from about 430–490 s to about 566–577 s. Once the mean reaches `test_experience.py`'s duration, the gate will start growing with the suite again.
- **`test_experience.py` starts late.** It has 31 classes, and most of its tests boot and stop their own runtime through function-scoped fixtures (`tests/test_experience.py:20-27`). Its 109 tests put it mid-queue under xdist's count ordering.
- **The busiest worker carries 120–200 s of non-test time,** about 70 s of which is collection (§3.5). The rest isn't attributed yet. P0.5 now records each worker's collection, start-wait, in-span gap and tail time in `gwN.json`, and `--gate-balance` reports them, so the first canonical gate that carries that data will attribute it.
- **The stale claim is corrected (P0.5).** The `scripts/select_tests.py --gate-balance` docstring and report note said the imbalance was "not of any single large file". The table above contradicts that. The text now says that `loadfile` never splits a file, so one file can set the critical path, and `--gate-balance` names that file for each run.

### 3.3 Anatomy of a runtime boot

The profile below boots `ProbOSRuntime(data_dir=tmp, llm_client=MockLLMClient())` the way the `test_experience.py` fixture does, in a single process on an idle host.

| Phase | Time | What dominates |
|---|---:|---|
| `import probos.runtime` | 1.1 s | Paid once per process |
| First `start()` in a process | 10.6–11.2 s | One-time per-process initialisation (not attributed) |
| Warm `start()` | 3.9–4.3 s | `CodebaseIndex.build()`: 2.0 s of CPU running `ast.parse` over all 963 files under `src/probos`. It is called synchronously on the event loop from `startup/agent_fleet.py:332-333`. After that come the hash-chained event-log inserts during agent onboarding and pool creation. |
| `stop()` | 3.1–3.2 s | 3.0 s of fixed sleeps in [shutdown.py](../../src/probos/startup/shutdown.py): `await asyncio.sleep(1)` (AD-435 grace, line 422) and `await asyncio.sleep(2.0)` (BF-296 Phase A grace, line 468). |

### 3.4 A/B experiment: remove only the two incidental costs

The experiment used a plugin that is not committed. It did two things and nothing else:

- it skipped exactly the two shutdown sleeps above;
- it memoised `CodebaseIndex.build()` once per process for the real package root, deep-copying the snapshot for each new instance.

The plugin counted its own effect, so a silent no-op couldn't be mistaken for a result. Both arms ran serially (`-n 0`) on the same tree, and both passed.

| Subset | Tests / boots | Baseline | Experiment | Change | Probe counters |
|---|---:|---:|---:|---:|---|
| `test_experience.py -k "TestPanels or TestShellCommands"` | 26 / 20 | 153.7 s | 57.5 s | −62.6% | 40 sleeps skipped; 1 real build, 19 memo hits |
| `test_knowledge_store.py -k "Runtime or shutdown or Shutdown"`, including `test_shutdown_flushes_knowledge` and `test_shutdown_persists_{workflows,trust,routing}` | 8 / 8 | 66.5 s | 27.3 s | −58.9% | 16 sleeps skipped; 1 real build, 7 memo hits |

The saving is **4.8–4.9 s per boot**. The boot files contain about 505 tests of 3 s or more, so the estimated saving is about 2,400 s of the 9,056 s suite, or about 27%.

This is an estimate, and three limitations apply:

- It assumes one boot per test of 3 s or more in the boot files. Some tests boot twice (the warm-boot tests); some slow tests don't boot at all.
- The A/B ran serially on an idle host.
- It measured both interventions together. The split between them comes from the §3.3 profile: about 3.0 s for the sleeps, about 2 s for the index build.

To tighten it, the factory (P1.1) counts boots and index builds exactly, and the Phase 1 decision uses interleaved full canonical gate arms (§5.2).

### 3.5 Collection

Every xdist worker collects the whole suite, and scheduling waits for the slowest one. Collection times, with everything deselected so only collection is measured:

| Setup | Cold assertion-rewrite cache | Warm cache |
|---|---:|---:|
| 16 workers in a freshly materialised worktree (what the gate uses) | 70.9 s | 44.3 s |
| Single process | 35.2 s | about 19.5 s |

One file loads the embedding model during collection. `tests/test_ad1138_records_semantic_index.py:730-733` calls `get_embedding_function()` inside a module-level `skipif`. As a result, every worker imports sentence-transformers, torch, and transformers (6.3 s of cumulative import time) and loads the model while it collects.

Ignoring that one file:

- cuts warm single-process collection from 19.6 s to 14.2 s (−28%);
- removes torch from collection entirely.

### 3.6 Scheduling simulation

The simulator replays xdist 3.8's `loadfile` policy against the baseline's per-test durations plus the measured 70 s of cold collection:

- files are queued in order of test count;
- a worker pulls its next file when it has two or fewer tests left.

For the baseline it predicts 994 s. The measured figure is 995 s (the busiest worker's busy time plus collection). The other ~95 s of the 1,090 s pytest phase is unattributed, so every projection below adds 95 s.

| Scenario (16 workers unless noted) | Simulated makespan | Projected pytest phase |
|---|---:|---:|
| Today (validation) | 994 s | 1,090 s (measured) |
| Duration (LPT) ordering alone | 942 s | about 1,037 s |
| Split `test_experience.py` into 4 files | 728 s | about 823 s (13.7 min) |
| Split + LPT ordering | 636 s | about 731 s (12.2 min) |
| Boot fix alone | 593 s | about 688 s (11.5 min) |
| Boot fix + LPT, no split | 510 s | about 605 s (10.1 min) |
| Boot fix + split + LPT | 485 s | about 580 s (9.7 min) |
| Same, 20 workers (if throughput scales) | 402 s | about 497 s (8.3 min) |
| Same, 24 workers (if throughput scales) | 347 s | about 442 s (7.4 min) |

- **Ordering alone does almost nothing, because the one file is the floor.** Even after the boot fix, `test_experience.py` (about 440 s) is still slightly above the balanced mean. That's why the split survives into Phase 1.
- **Treat the worker-count rows as best cases** — lower bounds on elapsed time. They assume per-test times don't grow as workers are added, and that the 95 s of unattributed time and the collection cost stay constant. The host has 16 physical cores, SMT gains on CPU-bound work are partial, and collection already slows under 16-way contention (§3.5). Only the P2.1 sweep can settle this.
- **The replay did not predict P1.4.** It treats each duration as fixed, but real durations depend on co-scheduling and on what the worker process ran before. Makespan models that ignore both mispredict, and the LPT rows above were not borne out: a same-tree A/B (see P1.4) found full LPT no faster than stock. Order changes are judged by an interleaved same-tree A/B of wall time and total busy, not by simulated makespan or balance.

### 3.7 Flakes and red time (September)

**Overall:** 129 canonical full gates took 38.8 gate-hours. 30 of them were red, one of them an interrupted run; that's 9.2 hours, or 23.7% of gate time. The AD-1270f target is under 10%.

**Confirmed flakes:** 8 commits went red and then green with no code change, costing 2.4 hours. A same-commit red on a ninth commit is excluded because that run was interrupted.

- **#1419 G-1/G-2 happened twice.** In `ad1246-full1` there were 48 failures, all on gw5. In `issue-1171` on 09-26 there were 58 failures, all on gw8; #1419 doesn't record this recurrence yet. Both runs followed the same chain:
  - A runtime boot raised one `FileNotFoundError` for `src/probos/_ad1256_injected_store.py` inside `CodebaseIndex.build()`. The file had been written into the tree under test by `tests/test_ad1256_store_registry.py:1306`, running on another worker.
  - After that, every later boot on the same worker failed with "YeomanAgent is a singleton; one instance is already live."
- **Single-test flakes:**
  - `test_ward_room.py::test_browse_threads_sort_recent` (also named as a known flake in `ci.yml`). *Fixed in Batch D:* two back-to-back `create_thread` calls can share one `last_activity`, and `ORDER BY last_activity DESC` has no tie-break, so SQLite returned the tied rows oldest-first (15 ties in 300 real-clock runs, every failure a tie). The test now drives a controlled clock. `test_unread_counts` and `test_list_threads_sorted_by_recent` had the same exposure and got the same fix; the latter passed only because SQLite's activity index happened to return tied rows newest-first.
  - `test_performance_p0.py::test_large_coalition_completes_quickly`. *Fixed in Batch D:* the wall-clock bound measured gate load (0.01 s idle, 2.66 s on a 16-worker gate). It is now `test_large_coalition_work_is_sampled_not_factorial`, which counts coalition-rule evaluations against a literal ceiling.
  - `test_ad1154_approval_inbox.py::test_a_raising_session_lookup_degrades_without_admitting_more`;
  - `test_ad1022_workstation_registry.py::test_api_dormant_when_disabled`;
  - `test_run_test_gate.py::test_main_collection_hook_cannot_remove_one_failing_node`.
  
  *Root cause found and fixed in Batch F:* all three are `WinError 10055` at test setup, while asyncio builds its self-pipe `socketpair()` (the third is a nested gate whose first worker failed to start). A per-test probe over 4,786 tests refuted the leak hypothesis: live sockets, loops and TCP rows went 0 → 0. The cause is churn. On Windows every asyncio loop's self-pipe is a loopback TCP pair, and closing a loop leaves a TIME_WAIT that holds an ephemeral port for 120 s. One worker created up to 785 loops in one 120 s window, so 16 workers can hold most of the 16,384-port range. `tests/fixtures/abortive_self_pipe.py` now closes only the self-pipe ends abortively (a plain `socketpair()` is untouched): 20 closed loops leave 0 TIME_WAIT instead of about 20. The same probe found pytest-timeout keeping two kernel semaphores per finished test (released now) and unstopped stores in `test_ad1019e` (stopped now).
- **A test close to its timeout:** `test_ad1192_owned_steps_store.py::test_1000_admitted_rows_reach_real_storage_verdicts_with_bounded_terminal_footprint` runs 171 s against the 180 s per-test timeout. In one red run (`ordinary-1129-7718fe7c-r2`), its xdist worker crashed while running it. The cause isn't attributed.

**Late discovery (replay).** Of the 27 September red gates with JUnit failures, 14 would have shown at least one failure from files whose historical total is under 5 s: 1,332 files and 628 s of CPU. Widening the lane to files under 20 s (1,429 files, 1,506 s of CPU) raises that to 21 of 27.

### 3.8 CI and parity

**Duration trend.** Median duration of successful push-to-main CI runs:

| Period | Median CI duration |
|---|---:|
| Sep 1–10 | 27.1 min |
| Sep 11–20 | 28.2 min |
| Sep 21–30 | 34.7 min |

- CI runs `-n auto` on a 4-vCPU runner, so it is limited by throughput and follows *total* test time rather than the critical path.
- The median rose 7.6 minutes in about three weeks. If that pace holds, CI reaches its 45-minute timeout within roughly a month. The latest run left 8.6 minutes of headroom.

**Local gates and CI don't run the same system:**

- CI sets `PROBOS_EMBEDDINGS=local`; the local gate doesn't.
- The local venv has one `probos.extensions` entry point installed, which is discovered at runtime boot. CI has none.

## 4. The plan

### Phase 0: critical path and flake root causes

Everything in this phase is small, independent, and test-side, apart from G-1b and G-2 in P0.2.

| # | Change | Expected effect | Quality guard |
|---|---|---|---|
| P0.1 | **Split `test_experience.py`** by class group into 3–4 files (shell commands; panels and renderer; memory, episodic and attention; roster and the rest). Move its module-level fixtures (`runtime`, `console`, `shell`) to a shared local module. The P1.4 class-grain allowlist is the alternative with no node-ID churn. | 18.2 → about 13.7 min on its own | Identical node count, with a 1:1 old→new node mapping checked from the collection manifests. No fixture scope changes. |
| P0.2 | **Fix #1419 G-1/G-2:**<br>• G-1: `test_ad1256_store_registry` injects into a copied tree under `tmp_path`, never into the tree under test.<br>• G-1b: `CodebaseIndex._analyze_file` tolerates a file that disappears between listing and reading.<br>• G-2: a failed `ProbOSRuntime.start()` releases the `YeomanAgent` singleton.<br>Add the 09-26 recurrence to #1419.<br>**G-2 status (2026-09-30):** deferred. Adversarial review blocked a first attempt that stopped only the pools. It left infrastructure tasks and non-daemon SQLite threads running, which kept a pytest process alive after its test passed. An unwire failure still kept the singleton. A late failure left `_started=True`. G-2 needs a designed, marker-free, reverse-order rollback of everything a partial boot started. G-1 removes the trigger measured in both cascades. | Removes the 48- and 58-failure cascades (two reruns, about 36 minutes in September) | One regression test per defect: for G-1, the store-registry test proves it never touches the tree under test; for G-1b, a build survives a file vanishing mid-scan; for G-2, a failed start followed by a fresh start succeeds in the same process |
| P0.3 | **Shorten one test's child process.** In `test_bf781_isolation_claims.py::TestRunDoesNotClaimItNeverRaises::test_the_behaviour_the_correction_describes`, change the child's `time.sleep(30)` / `timeout_seconds=30.0` to a few seconds. Today teardown takes 29.6 s against a 0.4 s call phase. That's the documented behaviour of `SubprocessSandbox.run`: the executor thread keeps running after cancellation. | −27 s | The assertion (CancelledError propagates) stays the same. The child must still outlive the cancellation point. |
| P0.4 | **Make the `test_ad1138` skip lazy.** Evaluate it in a fixture with `pytest.skip`, not in a module-level `skipif`. | Warm collection −28% per process, and no torch import during the collection barrier | Skip and run counts stay identical, with and without real embeddings |
| P0.5 | **Instrument the gate. Shipped in Batch E.**<br>• The per-worker payload in [_gate_pytest_plugin.py](../../scripts/_gate_pytest_plugin.py) gains a `timing` block (`schema_version` stays 1): monotonic and wall stamps for plugin load, session start, collection done, first test start, last test end and session finish, plus each file's first start, last end, summed duration and node count.<br>• A `timing` block is trusted only when it agrees with the worker's own `executed_nodeids` (same files, exact node counts, stamps in order, durations that fit their span); otherwise the worker is measured from JUnit.<br>• `select_tests.py --gate-balance` reports per-worker busy time (timestamps first, JUnit as the fallback), the critical-path worker and its dominant file. It names no critical path from incomplete evidence: workers, exit statuses, node uniqueness, counts and the union must match the collection artifact, or it reports an error and `busy: null`. Ranking and thresholds use raw seconds; only the display is rounded. The shared logic lives in [_gate_timing.py](../../scripts/_gate_timing.py).<br>• The stale docstring is corrected (§3.2). | Measurement only; it attributes the unexplained 95–200 s once a canonical gate carries the data | This is release-authority code, so it gets an adversarial review. Validation, exit codes and the merged collection artifact are unchanged, and so are the receipt's keys, status semantics and validation. The receipt's manifest hash covers the report-only budget like any other manifest field. |

### Phase 1: runtime boot cost and duration-aware scheduling

| # | Change | Expected effect | Quality guard |
|---|---|---|---|
| P1.1 | **Shared test runtime factory:** one `make_runtime(tmp_path, *, llm=None, config=None)` in `tests/conftest.py` or a `tests/support/` module. It replaces 27 locally defined runtime fixtures and the 240 `ProbOSRuntime(` constructions spread across 58 files. Migrate the heaviest boot files first; the 53 boot files hold 60% of suite time. | Enables P1.2–P1.3 and fixes the DRY problem | Migrate file by file; each migrated file's JUnit outcome must match |
| P1.2 | **Shutdown grace.**<br>• *Preferred:* replace both fixed sleeps with a bounded drain that returns once in-flight work is observably quiescent, capped at today's 1 s and 2 s. `IntentBus` already tracks in-flight dispatch (`close_to_new_dispatches`, `drain_pending_tasks`, `_pending_results` in `mesh/intent.py`); it needs a public idle predicate. But AD-435's 1 s grace covers in-flight DB writes more broadly, so the Architect must first list every writer that grace protects and make each one observable.<br>• *Fallback, if they can't all be observed:* two Pydantic fields beside `shutdown_drain_timeout_s`, defaulting to 1.0 and 2.0. The factory keeps **production timing by default**. Fast shutdown is opt-in per file. What shutdown leaves behind is not observed by any opted-in test body; pinned by the guard. Shutdown, persistence and concurrency tests keep production timing.<br>• **Shipped in Batch E: the fallback.** Two bounded fields, `shutdown_write_grace_s` (1.0) and `shutdown_dispatch_grace_s` (2.0), whose defaults are today's waits and also their maximums. A shared factory in `tests/fixtures/runtime_factory.py` zeroes both only for its own teardown stop, after the test body, and only for the files and modules that two guard tests pin: the files that ask for it, and the test modules that receive it through a shared fixture. The one intentional observer of what shutdown leaves behind is `tests/test_ad1270f_shutdown_grace.py`. First slice: the `test_experience*` family. The bounded drain was not selected: AD-435's writers (the periodic flush, the background loops and per-event fan-out tasks) expose no in-flight signal, and a 2 s drain cannot see tasks spawned inside handlers. P1.1 extends the opt-in file by file. | Preferred: about −3 s per boot, about −1,500 s of suite CPU. Fallback: less, depending on the opt-in coverage. | The production default stays unchanged and pinned (§5.3). What shutdown leaves behind is not observed by any opted-in test body; pinned by the guard. |
| P1.3 | **CodebaseIndex reuse.**<br>• *Test side:* the factory memoises one build per worker process and hands each runtime a deep copy (the index writes to `_caller_cache` at query time). Keep the memoised snapshot pristine. Key it on the source root plus a fingerprint of **every input `build()` reads**: all `*.py` files under the root, and the `_PROJECT_DOCS` files (`DECISIONS.md`, `PROGRESS.md`, the progress-era files, `roadmap.md`, `contributing.md`). Give the same memo to the function-scoped `index` fixture in `test_codebase_index.py`, which does a real build for each of its 38 tests, while keeping at least one test that exercises a real `build()`.<br>• *Production option for the Architect:* build off the event loop or lazily. Today it blocks the loop for about 2 s on every boot. | About −2 s per boot, about −1,000 s of suite CPU | Only the real, unmodified tree is memoised; indexes rooted in `tmp_path` bypass the memo. |
| P1.4 | **Duration-aware scheduler: start each worker on one of the heaviest files (shipped in Batch E).** An optional `pytest_xdist_make_scheduler` hook in `tests/conftest.py` delegates to `tests/fixtures/duration_scheduler.py`, which returns a `LoadFileScheduling` subclass. The root conftest is loaded on the controller for both the gate command and plain `pytest`, and xdist's own hook is `trylast`. The subclass changes only the order of the first distribution. xdist builds the whole work queue as usual, and the first assignment then re-orders it in place:<br>• each file is weighted by the seconds recorded in `tests/fixtures/file_durations.json`; a file the data doesn't know is weighted by test count × the suite's mean seconds per test (the mean, not the per-test median, which would send an unseen heavy file last);<br>• with K workers (K is `len(self.nodes)` once xdist has shut down any surplus workers), the K heaviest files go first, heaviest first, using a stable sort, so ties keep xdist's order, at the K boundary too. Every other file keeps xdist's count order. Each worker starts on one of the K heaviest files, and the top-up and later pulls take the rest in stock order. With no more files than workers this is the full descending order.<br>*Why not longest-first for every file:* full longest-first (LPT) was built first, measured, and replaced (see the effect column).<br>*Residual:* a heavy file with few tests that ranks below K keeps its late stock slot (`test_selfmod_e2e.py` ran last on gw1, from 461 s to 558 s, in the measured run). Promoting such files too is unmeasured and left out; it is worth its own A/B only if hybrid runs keep putting a below-K few-test file on the critical path.<br>*What it guarantees:* for a run that completes, every collected node runs exactly once, as with stock xdist. Crash handling is xdist's own and unchanged: it re-queues a crashed worker's unit, so the crashing node is retried. With `--maxfail` or `-x` (CI uses `--maxfail=10`) the scheduler stays on, and which nodes ran before the stop depends on the order, as with any order change.<br>`scripts/gen_file_durations.py` writes the durations file from a green canonical gate's JUnit and collection artifacts, and refuses unless the JUnit's testcases are exactly the collected nodes. The hook returns `None`, and xdist's stock scheduler runs, for any dist mode other than `loadfile`, for `--no-loadscope-reorder` (the only opt-out), for missing or invalid data, and when xdist's internals are missing. A `loadfile` session whose workers collected the same non-empty set prints exactly one `AD-1270f duration scheduler: heaviest K of N files first ...` line saying which case applied; an empty or mismatched collection never reaches the first distribution, so an enabled scheduler prints nothing then.<br>*Not built (optional):* an allowlist of files scheduled at class grain; promoting the files ranked below K. | **Measured, not simulated**: the earlier projection (13.7 → about 12.2 min, from the full-LPT replay) was not borne out. One tree (`9d305d61`), five back-to-back runs with the canonical pytest flags and P0.5 timing. **Non-canonical**: these are not gates. Pytest phase: stock 668.1 s and 689.9 s (busiest/mean 1.181 and 1.173; total busy 8,228 and 8,550 s); full LPT 721.4 s (its first run) and 689.1 s (1.035 and 1.027; 9,321 and 9,701 s); this rule 618.0 s (one run; 1.027; 8,660 s), 50–72 s faster than stock.<br>*Why full LPT was rejected:* it balances better but is no faster than stock (689.1 vs 689.9 s; 721.4 s was its first run), at about 13% more total busy. The extra time sits in the 1,331 files that took under 5 s in the first stock run, which LPT runs last (649 and 720 s under stock, 1,343 and 1,460 s under LPT, 736 s under this rule). That is consistent with per-process accumulation in workers that already ran the heavy runtime-boot files; it is the probable cause, not isolated. More extra time comes from subprocess-heavy files started together at t=0 (`test_run_test_gate.py`: 318 and 350 s under stock, 400 and 422 s under LPT). The Batch E gate passed its balance check (busiest ≤ 1.10 × mean) at 1.045 under LPT, so balance alone was the wrong signal.<br>This rule is one run; the batch PR carries the replication and the canonical gate. | It changes scheduling order only. The wrapper's collection-identity and exactly-once checks are unchanged and still judge every completed run. Order changes are judged by an interleaved same-tree A/B of wall time and total busy, not by balance or simulated makespan. |
| P1.5 | **Run the equivalence protocol (§5)** before and after P1.2–P1.4. | — | §5 |

### Phase 2: scaling, outliers, CI

| # | Change | Expected effect | Quality guard |
|---|---|---|---|
| P2.1 | **Worker sweep:** 16, 20 and 24 workers on the same commit and node manifest, at least 3 canonical runs each. Record wall time, peak RSS, and red/flake count. Adopt the highest count that adds no flakes, and change `pyproject.toml` `addopts` and the wrapper's `--workers` default together. | At best about 9.7 → 8.3 min | No flake increase. BF #466 and BF-657 are why this is measured, not assumed. |
| P2.2 | **Subprocess-heavy outliers.** Rule: a real process stays wherever the process boundary *is* the behaviour under test. Only collapse repeats where the process is just transport.<br>• `test_phantom_api_precheck_kwargs.py` (165 s): every helper call starts a fresh interpreter that re-parses `src/probos`, and one test makes five calls (71 s). The same pattern appears in `_method_calls` and `test_ad685c_phantom_type_shape`. The helper's parsing logic is the behaviour here and the process is transport. So call it in-process against a session-cached parse, and keep real CLI and real `pwsh` wrapper tests for each distinct CLI/wrapper behaviour.<br>• **Slice 1 shipped: the phantom-precheck kwargs tests.** Reading the tree corrected the premise. Test 4 makes six helper calls, not five (five fences and one masked body). `test_phantom_api_precheck_method_calls.py` and `test_ad685c_phantom_type_shape.py` have nothing to convert: the first makes one direct CLI call, kept real because it is the only real-CLI test on a UTF-8 archived prompt, and the second makes none (its `pwsh` self-test stays real). So the ten helper calls in kwargs tests 2–6 now run the helper's real `main()` in-process, through `tests/fixtures/phantom_helper_memo.py`: a private copy of the helper, stdin swapped, stdout and stderr captured. The parse cache is the helper's own. It is reused only while the content digest of the helper and of every `*.py` under `src/probos` is unchanged; any change loads a fresh instance, and the module-scoped fixture releases it at teardown. The kwargs file launches one direct helper process instead of 11 (test 1 stays the real CLI test). The `method_calls` CLI test and all five `pwsh` wrapper tests are unchanged, and so are node IDs, assertions and timeouts. *V7:* 17 helper mutants (the `main()` plumbing, the kwarg logic, the index builders) ran against kwargs tests 1–6 before and after. 16 are killed in both arms and 1 survives in both (the exit-status line, which no kwargs test observes). The process-entry mutant is killed by test 1 in both arms. A premise probe on the cached-index hit survives before and is killed by the warm in-process tests after. *Measured alone, 3 runs each:* the kwargs file 172.3 s → 53.2 s; tests 2–6 call time 121.2 s → 11.1 s (−91%); the other two files are untouched controls. *Stated gap:* the cache's invalidation is proven by a recorded probe, not a committed test, because the node set stays fixed.<br>• `test_run_test_gate.py` wave-orchestrator tests (about 14.5 s each): build the template git repo once per session and copy it per test. The git state stays identical, and so does the coverage.<br>• `test_ad1205_fault_paths.py` (231 tests with a 1.0 s mean, some of them spawning real sandbox children): audit first. Keep every behaviour-distinct real-child case, and collapse only identical repeat launches.<br>Both this file and `test_phantom_api_precheck_kwargs.py` caught a real defect in September (§9.3), so prove any reduction in either with targeted mutation first (V7). | About −250 to −400 s of CPU, mostly helping CI throughput | Every behaviour-distinct cross-process case keeps a real process |
| P2.3 | **Whole-tree scanning tests** (`test_ad1270b_architecture_fitness.py` 74 s, `test_ad1256_store_registry.py` 80 s, `test_ad1270b_seam_contracts.py`, `test_codebase_index.py` 95 s): cache the real-tree scan once per worker session. Tests that prove a checker "can fail" mutate a *copy* (see P0.2). | About −150 s of CPU | Each checker still has a real-tree test |
| P2.4 | **Product-performance leads the tests surfaced.** Profile these first, and file only if confirmed:<br>• `test_ad1242_crew_verifier_trace.py::test_public_future_render_bounds_entire_redacted_section[20000-*]` takes 11.6–14.2 s in isolation, against about 1.2 s for the other cases. That's about 3.5× the input for 11× the time, which is consistent with quadratic cost in the render or redaction path.<br>• The 1000-row capacity test spends about 57 ms per committed transition. | Depends on the findings | No N reduction, no timeout change |
| P2.5 | **Fix each confirmed single-test flake (§3.7) at its root:** ordering, clocks, subprocess timing. | Part of the 2.4 h of confirmed-flake reruns | Each fix comes with a regression test |
| P2.6 | **Hermeticity.** *Shipped in Batch D.*<br>• Add `os.environ.setdefault("PROBOS_DISABLE_OVERLAY", "1")` to `tests/conftest.py`, next to BF-245's NATS default, so local gates boot the same OSS runtime as CI. Tests of the extension seam keep opting in. The default is declared in `config-profiles.yaml` `ci_divergences` (new `first-party-env` mechanism), so deleting it fails `check_config_profiles.py`.<br>• Don't adopt `PROBOS_EMBEDDINGS=local` in the canonical gate (§6). | Local/CI parity. No measurable time saving (the installed hooks cost about 1 ms per boot) | — |
| P2.7 | **CI sharding (shipped in Batch F).** `python-tests-shard` runs the suite as three file-level shards (matrix 1–3, `fail-fast: false`), and a final `python-tests` job proves exactly-once execution across them the way the wrapper does per worker: every collected node executes exactly once (an execution *count* of 1, not just set union), and shards don't overlap.<br>• Each shard collects the whole suite and keeps its own files under the unchanged `-n auto --maxfail=10` command; `--maxfail=10` is each shard's own budget.<br>• `scripts/ci_shards.py` assigns files longest first on the millisecond durations from `tests/fixtures/file_durations.json` (P1.4); a file the data doesn't know weighs its node count × the known files' mean milliseconds per node. `scripts/_ci_shard_pytest_plugin.py` (loaded with `-p`) filters each worker's collection, refuses any other hook that removes, adds or renames a node, and writes per-worker evidence: the full-collection and assignment digests, plus every setup report with repeats kept.<br>• `python-tests` keeps its check name, runs under `always()` and fails unless every shard succeeded. It then runs `scripts/ci_shards.py verify` on the downloaded evidence: identical independent collections, a recomputed disjoint assignment, and an execution count of exactly 1 per node.<br>CI evidence is not release authority; the canonical gate is unchanged. | About 36 → 10–12 min per run (a projection; no sharded CI run has been measured yet) | A per-node count check and a duplicate check across shards (`scripts/ci_shards.py verify`), pinned by `tests/test_ci_shards.py` and `tests/test_ci_shard_pytest_plugin.py` |

### Phase 3: keep it fast

| # | Change |
|---|---|
| P3.1 | **Duration budget in the wrapper summary.** List tests over 10 s, files over 120 s or over 50% of mean worker busy time, and any file that becomes the critical path. Start report-only. Once the baseline is stable, fail on *new* offenders unless they're listed with a reason.<br>**Report-only half shipped:** once collection validation has succeeded, the gate manifest carries `duration_budget` (otherwise it is null and `duration_budget_skipped` says why) and the console prints one `DURATION BUDGET (report-only)` line. It reads only the validated `gw0..gw(N-1)` files, and its cost is linear in that evidence: 0.14 to 0.29 s over seven runs on a synthetic 37.9k-test, 16-worker gate. Neither changes an exit code, the manifest's `error` or `summary`, or whether a receipt is issued. The receipt's keys, status semantics and validation are unchanged, and its manifest hash covers the budget like any other manifest field. Enforcement and the offender allowlist are not started. |
| P3.2 | **Refresh the durations file** whenever the critical-path worker goes above 110% of mean busy time, and at least weekly. Run `python scripts/gen_file_durations.py --junit <gate>.xml` on the JUnit of the latest green canonical gate. It reads the sibling `<gate>.collection.json`, writes `tests/fixtures/file_durations.json`, and refuses to write if any test failed or the JUnit's testcases aren't exactly the collected nodes. The refreshed file is a tracked change under `tests/`, so it needs its own broad gate before it is pushed. |
| P3.3 | **Add test-writing rules to the Testing Standards:**<br>• boot runtimes only through the factory;<br>• no fixed sleeps of 0.5 s or more — today there are 114 `asyncio.sleep(≥0.5)` lines in 50 files and 85 `time.sleep(` call sites in 35 files. Use one shared `wait_until` helper instead of the six private copies;<br>• never write into the tree under test;<br>• keep a real subprocess wherever the process boundary is the behaviour under test, and never respawn a process just as transport. |
| P3.4 | **Fail-fast lane (option; needs a decision).** An advisory wrapper mode that runs files with historical duration under 5 s (1,332 files, about 628 s of CPU) before the full gate. On the September replay, it would have exposed 14 of 27 red gates in about 2 minutes instead of about 18. It isn't release authority and adds about 2 minutes to green runs. Keep it out of canonical preflight, which AD-1270f caps at 90 s. |
| P3.5 | **Feed the AD-1270f selector shadow series.** It has 1 of its 20 eligible rows, and none since 2026-09-02. This is related work, not part of this plan's time budget. |

## 5. How quality is verified

1. **Node-set invariance.** Every change keeps the canonical collection's node count. P0.1 also ships a 1:1 mapping from old to new node IDs.
2. **Outcome invariance (A/B).** On the same commit, run full canonical gates with and without each Phase 1 change, and interleave the arms. Compare the normalised **`nodeid → outcome` map** (passed, skipped with its reason, xfailed, failed), not aggregate counts. The gate checks collection and execution identity, not per-node outcomes. Only predeclared differences are allowed. A new failure is investigated as a latent isolation defect, not reverted on sight: new file co-locations can expose cross-file pollution, as the YeomanAgent singleton did.
3. **Production-default pins.** One test asserts that a default-config shutdown still grants the 1 s and 2 s grace, or the drain cap. Another asserts that a default `CodebaseIndex` still builds from disk.
4. **Test-profile drift guard.** A test asserts that the factory's config differs from `SystemConfig()` only in allowlisted fields. Nobody can quietly turn off a subsystem to make a boot test faster.
5. **Targeted mutation, only for the new guards** (per the Captain's rule):
   - set the default grace to 0 → the pin fails;
   - make the memo return a shared, un-copied snapshot → an isolation test fails;
   - drop a file from the scheduler queue → wrapper validation fails.

   Run the unmutated baseline first. Use single-line anchors and mutate in place with a `.mutbak` backup.
6. **Track the AD-1270f metrics:** red-time share, late-discovery rate, and full-gate critical path on the same host fingerprint and node-manifest hash.

## 6. Explicitly rejected

- **Deselecting or skipping `slow` tests in the canonical gate, changing per-test timeouts, or shrinking capacity tests.** Each breaks the AD-1270f acceptance criteria.
- **Sharing one runtime across a module or class.** It breaks isolation, and the YeomanAgent cascade shows what happens.
- **`PROBOS_EMBEDDINGS=local` in the canonical gate.** Real-embedding tests such as `TestSemanticQuality` would turn into skips.
- **Pruning or merging fast tests to save time.** 85% of tests take 3.7% of the time. Retiring a test for value reasons is a separate question (§9), with its own proof protocol.
- **Relaxing SQLite durability for the hash-chained event log.** After P1.2 and P1.3, its per-row commits are the next-largest boot cost. But it's an audit store, so any change there is a Captain decision, not a test optimisation.
- **`-n auto` or `-n 32` without the P2.1 sweep.** BF #466 and BF-657 already recorded worker crashes and timing flakes under oversubscription.
- **Using impact selection for release.** The AD-1270f selector stays advisory.

## 7. Risks

| Risk | Mitigation |
|---|---|
| New worker co-locations (P0.1, P1.4) expose latent cross-file pollution | Treat each case as a pre-existing isolation defect, and run the A/B at least 3 times before adopting |
| The durations file goes stale | Balance degrades, but no test is ever skipped. P3.2 refreshes it, and P0.5 detects drift. |
| The custom scheduler depends on xdist's `LoadFileScheduling` internals | A test pins the xdist minor version it was written against, and the hook falls back to the stock scheduler if the base API is missing |
| The bounded drain (P1.2) changes shutdown timing in production | It can only wait *less* than today's fixed sleeps, and only when nothing is in flight. The fallback keeps production byte-identical. |
| Windows timer, Defender, and thermal variance distort benchmarks | At least 3 runs per arm; report the median and spread; same host fingerprint |

## 8. Suggested order

1. **P0.2 and P0.3.** Flake root cause and the 27 s teardown. Each is independent and small.
2. **P0.1, then P0.4 and P0.5.** Taken in isolation, P0.1 gives the largest wall-clock drop in the plan.
3. **P1.1 → P1.2 → P1.3**, migrating the heaviest boot files first. Run the §5 A/B after each step.
4. **P1.4.**
5. **P2.1 and P2.7.** CI urgency: roughly a month to the timeout if September's pace holds.
6. **The rest of Phase 2, then Phase 3.**

Batches follow the repository's batched-execution rule: up to three bounded items, focused tests, a scoped adversarial review for each item, and one canonical gate per batch.

## 9. Test value and redundancy review

The question here: are any tests duplicative, or not providing value? Two methods answered it.

- **A static census of every test function**, joined to the baseline gate's timings: 27,183 functions, 37,842 nodes, 9,064 s. Each category below was checked by reading flagged tests before it was reported.
- **Gate history**: what each September red gate led to — a product fix, a test edit, or nothing.

### 9.1 Headline

- **Redundancy isn't where the time is.** Removing every literal duplicate and every test that can't fail would save about 13 s of 9,064 s. Even the entire set of slow tests with weak or no assertions (§9.2) is only 3.8% of suite time.
- **The census did find real value defects, in small numbers:**
  - tests that can't fail;
  - tests whose names claim a scenario they never set up;
  - slow tests that start a full runtime they don't use, or assert almost nothing.
- **History shows the broad suite catches real, cross-cutting defects.** Untouched, pre-existing test files led to 11 product fixes in September.
- **The same cheap pinning and contract tests also cause most of the churn.** In 19 events, an untouched, pre-existing test was fixed by editing only the test. The fix for that is running those tests earlier, not deleting them. "It never fails" is never evidence that a test is worthless.

### 9.2 Static census

| Category | Functions (nodes) | Time | Verified examples |
|---|---:|---:|---|
| **Literal duplicates:** same body, same decorators, and every global and fixture it reads resolves to an identical definition | 34 extra copies in 25 groups (34) | 12.6 s | `test_format_duration.py` ↔ `test_temporal_context.py` (four identical tests); three slice tripwires copied verbatim into all five `test_ad1270e2{e..i}_*_models.py` files (one of them, `test_the_index_still_sees_a_never_moved_model`, costs about 3.1 s per copy, 12.4 s for the four extra copies) |
| Body-identical but different data — *not* duplicates | 59 of the 83 body-identical groups | — | The data comes from `parametrize` decorators, per-file constants, or per-file fixtures, e.g. the three `test_ad1159_work_permits` TTL tests |
| Near-duplicate shape (same structure, different literals) | 1,056 extra copies in 702 groups (1,235) | 402 s | Candidates for parametrization. Parametrizing changes no runtime, so this is maintainability only. |
| **Every assertion is a tautology** (the test can't fail) | 3 | ~0 s | `test_dispatch_wiring.py::TestRuntimeWiring::test_runtime_has_build_queue_field` and `…_build_dispatcher_field` both assert `hasattr(ProbOSRuntime, '__init__')`. `test_ad632h_parallel_dispatch.py::TestBackwardCompatibility::test_handler_protocol_unchanged` asserts `hasattr(SubTaskHandler, '__call__')`. None of them checks what its name claims. |
| **Same body, different claimed scenario** | at least 4 pairs (including the `test_dispatch_wiring` pair above) | ~0 s | `test_multi_agent_replay_dispatch.py::test_compound_replay_no_registry` copies `…_no_intent_bus` (`MagicMock(spec=[])`). None of the other 12 test call sites of `_execute_compound_replay` sets up an intent bus without a registry. `test_ad596e_skill_validation.py::test_validate_spec_valid_with_hyphens_and_digits` uses the same input as `…_valid_name`. `test_graduated_zones.py::test_get_zone_returns_current_zone` copies `…_new_agent_starts_green`. |
| Docstring claims more than the test checks | at least 1 | ~0 s | `test_codebase_index.py::test_find_tests_for_panels` says it "finds test_experience.py" but only asserts `isinstance(tests, list)` |
| Either/or ("hedged") assertions | 217 (219 asserts) | 351 s | Some just allow for wording variants. Others accept nearly any outcome:<br>• `'Pool Scaling' in output or 'Scaling' in output` — the first branch implies the second;<br>• `result is None or result.verdict == 'error'`;<br>• `test_dag_proposal.py::test_plan_with_text`'s `… or "read" in output.lower()` |
| No assertion at all | 154 (167) | 44 s | Mostly "does not raise" smoke tests. 4 of them are slow (37 s). For example, `test_ad843c2_device_consensus.py::test_store_device_consensus_episode_honest_degrade_when_no_memory` starts a runtime (11.5 s) to call one private helper and asserts nothing. |
| Only weak assertions (`isinstance`, `is not None`, bare truthiness) | 868 (943) | 351 s | 36 of them are slow (307 s), and 29 of those start a runtime. For example, `test_self_mod.py::TestRuntimeSelfMod::test_runtime_creates_pipeline_when_enabled` spends 13.8 s to assert two attributes are not `None`. |
| Starts a runtime it never uses | 2 | 20.7 s | `test_experience.py::TestReflectCapability::test_render_dag_result_{with,without}_reflection` request `runtime` but only render a hand-built dict. Both sit in the critical-path file. (A third flagged case, `test_dag_proposal.py::test_plan_with_text`, is a false positive: its `shell` already needs the same runtime instance.) |
| Text-scan pins (read file text, assert membership) | 441 (506) | 199 s | These pin the source (307 functions, 121 s) or docs and prompts (121 functions, 111 s). Keep them where the text *is* the contract, as in AD-1270g's executable documentation. Otherwise prefer a behavioural test. |

### 9.3 What September's red gates say about value

Of the 27 September red gates with JUnit failures, 7 were same-commit flakes. The other 20 were compared with the next green gate in the same worktree.

| What changed before green | Gates |
|---|---:|
| Product code only; the failing tests were untouched (a defect caught) | 3 |
| Product code and the failing tests | 3 |
| Only tests | 13 |
| No later green gate | 1 |

Counting per failing test file (52 file-level failures), each file was compared with the candidate's base on main:

| Failing file | Resolved by | Files |
|---|---|---:|
| Pre-existing and untouched by the candidate (44) | Product fixed, test unchanged: **defect caught** | 11 |
| | Both product and test changed | 12 |
| | Only the test edited: **change detector** | 19 |
| | Neither | 2 |
| Pre-existing, but edited by the candidate | — | 6 |
| New in the candidate | — | 2 |

- **The defect catchers** span 11 files. They include the golden and pinning tests `test_ad1179_tool_schema_golden.py` and `test_ad1152_agentic_correlation.py`, and both slow subprocess files, `test_ad1205_fault_paths.py` and `test_phantom_api_precheck_kwargs.py`.
- **The change detectors** span 17 files. They include `test_layer_boundaries.py` and `test_ad1164_continue_or_ask.py` (twice each), plus `test_ad1152_agentic_correlation.py` again. Several are deliberate governance tripwires: updating `test_layer_boundaries.py` *is* the review step for a new cross-layer import. Their cost is a full red gate each, about 18 minutes.
- **Both groups are mostly cheap.** 14 of the 17 change-detector files take under 20 s per gate (9 under 5 s), and so do 9 of the 11 defect-catching files (7 under 5 s). The P3.4 fast lane would surface both in about 2 minutes.
- **This changes P2.2.** Any reduction of real-process cases in `test_ad1205_fault_paths.py` or `test_phantom_api_precheck_kwargs.py` must first be proven by targeted mutation not to lose detection, because both files caught real defects in September.

### 9.4 Actions

| # | Change | Effect |
|---|---|---|
| V1 | **Fix the tests that can't fail or don't set up what they claim.**<br>• Rewrite the three tautologies so they assert what their names say.<br>• Give `test_compound_replay_no_registry` an intent bus without a registry, and add the inverse case.<br>• Make `test_find_tests_for_panels` assert the finding its docstring promises, or correct the docstring.<br>• Replace the two copied cases (`ad596e`, `graduated_zones`) with the case each name describes. | Quality. No time change. |
| V2 | **Drop the unused `runtime` parameter** from the two `TestReflectCapability` tests. | −20.7 s of CPU, all of it on the critical-path file |
| V3 | **Strengthen the 40 slow weak or no-assert tests.**<br>• Replace presence checks with type, identity and wiring checks.<br>• Replace "must not raise" with an assertion on the degrade outcome (e.g. no episode stored, warning logged).<br>• Pin hedged either/or assertions to the one deterministic outcome, where there is one.<br>• If a test needs only an object rather than a started runtime, use the lightest fixture that still exercises the behaviour under test. | Quality; some time |
| V4 | **Remove the 34 literal duplicate copies,** keeping one of each. Move the shared `test_ad1270e2*` tripwires into one parametrized module. Parametrize near-duplicate shapes when a file is next touched.<br>*Batch D:* the cross-file copies are gone, each re-verified identical by AST (body, decorators, parameters, transitive globals and fixtures). The `test_ad1270e2*` tripwires now live only in e2e, since every copy checked the same package-wide property. The five same-file pairs were mostly V1 defects rather than duplicates: four now set up the case their name claims (each kills a mutant the old body survived), and one was a true duplicate and was removed. The 16 changed files went from 1,189 to 1,163 nodes: 26 copies retired, plus one test renamed (27 node IDs removed, 1 added). V7 evidence for every retirement (37 single-line mutants over 12 groups; the twin and the retired copy have identical kill sets in all 56 comparisons) is on #1448. No measurable time saving: the shared `config_schema` setup moves to whichever test requests it next. | Planned −12.6 s (JUnit time attributed to the copies); realized: no measurable saving. Maintainability |
| V5 | **Wiring census (option; needs a decision).** Fourteen slow wiring-presence tests ("runtime creates X…", 139 s; 8 of them have only weak assertions) each start a runtime to check that a service was created. One table-driven wiring test per config profile could keep every assertion (strengthened) and report all missing services at once. It merges tests, which §2 otherwise avoids for time savings: fewer runtime starts, but coarser failure granularity. | Up to about −130 s of CPU |
| V6 | **Tag pinning and contract tests** (e.g. `pytest.mark.contract`), so the P3.4 fast lane selects them by intent rather than by duration. Give each golden file a one-command, reviewed regeneration path. | The 19 change-detector events would surface in about 2 minutes instead of about 18 |
| V7 | **Retirement protocol for any test:**<br>1. name the stronger test that covers the same behaviour;<br>2. run targeted mutation on the code under test and show the retiring test kills no mutant the remaining tests miss (baseline first; single-line anchors);<br>3. record the node-set change in the PR.<br>Never retire a test because it "never fails." | A guardrail |

V1 and V2 are small enough to join Phase 0. V3–V6 fit alongside P1.1, since the factory migration touches the same files.

## 10. Execution log

Every row was measured on the reference host by a canonical gate, with a receipt bound to the commit.

| Step | Change | Canonical gate (pytest phase) | Busiest worker vs mean | Notes |
|---|---|---:|---:|---|
| Baseline | `origin/main` before execution (`issue-1131-r2`) | 1,090.5 s | 925 s vs 566 s | `test_experience.py` on the busiest worker |
| Batch A (#1443) | #1419 G-1/G-1b, P0.3, P0.4, V2, one V1 fix | 980.4 s | not analysed | Merged. G-2 deferred (see P0.2). |
| Batch B (#1445) | P0.1 split, the other V1 fixes | 763.3 s (−30% vs baseline) | 653.5 s vs 575.3 s | Spread 548–654 s across 16 workers. Found #1444. |
| Batch C (#1446) | P1.3 test-side CodebaseIndex memo | 677.7 s (−38% vs baseline) | 556 s vs 468 s | A/B on 20 runtime boots: 173.8 s → 121.1 s (about 2.6 s per boot). A rerun under host contention measured 762.1 s with uniformly higher CPU. |
| Batch D (#1448) | P2.6 hermeticity, V1 pairs, V4 copies, two flake root causes | 834.4 s (shared host) | — | Quality and parity, not speed. Other agents' test runs shared the host during the gate, so its time is not comparable. |
| Batch E | P1.4 scheduler (each worker starts on one of the K heaviest files, the rest keep xdist's order; replaced full LPT after a same-tree A/B), P1.2 first slice, P0.5 timing + report-only P3.1 budget | see the Batch E PR | see the Batch E PR | Full LPT was built first and replaced before the canonical gate: it balanced best but was no faster than stock (see the P1.4 row). The batch PR holds the canonical gate and the A/B replication. Before: Batch C's gate (`a2d14224`), busiest 556 s vs mean 468 s (1.19x); the durations file was generated from that gate. |
| P2.2 slice 1 | Phantom-precheck kwargs tests 2–6 call the helper's `main()` in-process, against a cache keyed on file content (`tests/fixtures/phantom_helper_memo.py`). Test 1, the `method_calls` CLI test and the five `pwsh` wrapper tests stay real processes. | see the PR | — | Direct helper launches in the kwargs file: 11 → 1. Alone, median of 3 with the range (pytest-reported): kwargs 172.3 s (172.0–178.0) → 53.2 s (51.9–67.9); tests 2–6 call time 121.2 s → 11.1 s (−91%); controls `method_calls` 25.4 s → 25.6 s and `ad685c` 13.8 s → 13.4 s. V7: 17 mutants, the same 16 killed before and after (the process-entry mutant only by test 1 after), premise probe survives before and is killed after (matrix on the PR). The base weight in `file_durations.json` (142.5 s, from Batch C's gate) is not refreshed here; P3.2 regenerates it. The canonical gate and the file's span in its P0.5 timing block are on the PR. |

**Not executed yet, and why:**
- **P1.1 (shared runtime factory):** P1.2 shipped its factory (`tests/fixtures/runtime_factory.py`) and opted in the `test_experience*` family; P1.1 extends the opt-in file by file, each reviewed against the guard's effective-module set.
- **P2.7 (CI sharding):** built and reviewed; it ships in its own batch so its CI effect is measured on its own.
- **P2 and P3:** the worker sweep needs dedicated machine time.
- **P2.2 (the rest):** the `test_run_test_gate.py` template repo and the `test_ad1205_fault_paths.py` audit are still open. The audit needs the same V7 proof before any real-child case is collapsed.
- **V3, V5, V6:** V5 and P3.4 still need decisions. V3 and V6 fit alongside P1.1.
## Appendix: reproducing the evidence

- **Per-worker busy time:** `python scripts/select_tests.py --gate-balance <run>.collection.json <run>.xml` does this join and uses the `timing` block of each `gwN.json` when it has one. By hand, join the `executed_nodeids` in `<run>.collection-workers/gw*.json` with the JUnit `time` attributes of the same run. Map `file` + `classname` + `name` to node IDs the way `scripts/_gate_timing.py::junit_node_id` does (`select_tests.junit_node_id` re-exports it).
- **Scheduling simulation:** replay xdist 3.8 `LoadScopeScheduling.schedule()` and `_reschedule()`:
  - work units are files;
  - the queue is sorted by test count (`loadscopereorder` defaults on);
  - a worker pulls its next unit when two or fewer of its tests are pending.

  Validate the replay against the measured baseline before using it for projections.
- **Boot anatomy:** use cProfile, plus an await-chain sampler that walks `cr_await` from the `start()`/`stop()` task every 10 ms.
- **A/B probe:** a pytest plugin loaded with `-p`. It short-circuits `asyncio.sleep` only when called from `probos/startup/shutdown.py` with 1 or 2.0 s, memoises `CodebaseIndex.build` for the real package root, and prints its own counters so a no-op is visible.
- **Collection:** `pytest tests/ -n 16 --dist=loadfile -o addopts= -k <no-match>` in a fresh `git worktree`, run cold and then warm. For the import profile, use `-X importtime` with `-s`, because capture swallows the import log.
- **Flakes:** group gate manifests by `snapshot_before.head`, excluding interrupted runs (`interrupted: true`, exit 130). A head with both red and green full gates is a confirmed flake.
- **Value census (§9.2):** an AST pass over every `test*` function in `tests/`, joined to JUnit times by file, class and base name.
  - It classifies assertion strength, fixture use, and whether a test reads file text.
  - Duplicate candidates are grouped by body hash, then kept only if decorators, same-file fixtures and every free global resolve to identical definitions in each file.
  - Every category was checked by reading flagged tests. False positives found by that reading are reported as such (e.g. `test_plan_with_text`).
- **Red-gate value (§9.3):** for each non-flake red gate, take the next green gate in the same worktree and `git diff --name-only` the two heads. Classify each failing test file against the candidate's base: the first ancestor on `origin/main`'s first-parent line.
