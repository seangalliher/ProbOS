# BF-904b: the sealed-core observation can fire, refusals and syntax state are kept apart, a build in review holds its files, and the visiting builder works from whole files

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21 (Amendment A1, §16; Amendment A2, §17)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22 (Amendment A3, §18)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22 (Amendment A4, §19)

**Status:** build-ready on the merged main (after BF-901 S3). **Closes #1585** (BF-904b: items 2, 4, 6 and 7; BF-904a did 1, 3 and 5). **Tier HIGH** (the build pipeline; item 2 is a governance control; M2 changes when model-written code runs). No new AD or BF number. **Base:** drafted on HEAD `90a9e040`, tree `39b6ec2b73372aa40efc8a883fa494cd3a286061` (`origin/main` `ad5f820c` plus BF-901 S3, which touches nothing in the build pipeline). **Source:** the Architect's read-only consult of 2026-10-21.

**Tests:** three new files. M1 `tests/test_bf904b_sealed_core_observation.py`: 11 functions, 30 cases (S9 added by Amendment A2; S9 widened and S10 added by Amendment A4). M2 `tests/test_bf904b_fix_loop_state.py`: 8 functions, 15 cases (F6 `[directory]`, F7 and F8 added by Amendment A3). M3 `tests/test_bf904b_dispatch_and_visiting.py`: 5 functions, 11 cases. **56 cases in 24 functions.** Updated where they pinned the old behaviour, each with an inline reason: `tests/test_ad481_extensions.py` (2 functions, M1), `tests/test_bf898_fix_loop_grader_protection.py` (1, M2; its injection point moved by Amendment A3), `tests/test_bf896_executor_identity_and_blocks.py` (2: the signature pin in M1, 7.5b, added by Amendment A1; the seed test in M3, 7.12).

**Line endings:** every edited file's working copy is CRLF (`core.autocrlf=true`). The SEARCH blocks are written with LF; match and write with the file's own line endings. The new test files are written LF and checked in as git normalises them.

---

## 0. Premise: what is still present on this tree

The issue's anchors are on `28a3786b`, before BF-904a rewrote large parts of `builder.py`. Each clause, re-read on `90a9e040`:

| Clause | State | Evidence |
|---|---|---|
| (2) `_check_sealed_path` returns when `runtime is None` | present | `builder.py:3098-3099` |
| (2) neither production caller passes `runtime` | present | `routers/build.py:441-448`, `build_dispatcher.py:215-222`; the third caller, `BuildPipeline`, passes one (`build_pipeline.py:98`, built at `runtime.py:3552`) |
| (2) `is_sealed_path` gets the absolute path | present; BF-904a moved the call sites and added a fourth | `path = Path(work_dir) / change["path"]` at `builder.py:3264` and `:3518`; calls at `:3336`, `:3358`, `:3543`, `:3549`; `sealed_core.py:56-70` matches repository-relative globs |
| (2) coupled, found here | `load_sealed_globs()` with no argument reads `config/sealed_modules.yaml` relative to the process's working directory | `sealed_core.py:20`, `:30` |
| (4) `validation_errors` only grows; `elif validation_errors:` blocks | present; BF-904a put more refusal kinds into the same list | appends at `builder.py:3255`, `:3262`, `:3271-3300`, `:3326`, `:3353`, `:3377`, `:3504`, `:3512`, `:3539`, `:3562`; block at `:3627-3629` |
| (4) `all_changed_files` computed once, before the loop | present | `builder.py:3427`, loop `:3430` |
| (6) `has_footprint_conflict` checks `dispatched` and `building` only | present | `build_queue.py:154` |
| (6) `_git_create_branch` force-deletes an existing branch | **gone** (BF-904a A4, D31, `DECISIONS.md:170`): an existing branch of the name refuses the build before any write | `builder.py:1665-1679` |
| (7) excerpts reach `seed_session_directory` and `adapter.execute` | present | `builder.py:2370-2379`, `:2432`, `:2443` |
| (7) `transporter_complete` changes are not normalised | present | `builder.py:2651-2667` against `:2694` |
| (7) the base check refuses a whole-file change made against an excerpt | present (BF-896) | `builder.py:3287-3296`, `:3310-3315` |

The one `branch -D` left (`builder.py:3728`) deletes `build_branch`, which `_git_create_branch` created in this call (it returns success only after `checkout -b` of a name that did not exist, `:1673-1679`). It runs only when nothing was committed (`restore_tree`, `:3706`) and the return to the original ref succeeded (`:3718-3726`). Item 6's second clause is recorded as met by BF-904a, not rebuilt.

## 1. Problem

1. **Item 2.** With `extensions.enforce_sealed_core` on, nothing is observed. The /api/build resolve route and the build dispatcher pass no runtime, so the check returns at once. `BuildPipeline` passes one, but the check hands `is_sealed_path` an absolute path, which matches no glob. The default policy path also depends on the process's working directory.
2. **Item 4.** One list holds two kinds of state. A refusal is permanent; a syntax error is a property of a file's current text. A syntax error that a repair fixed still blocks the commit, and a file a repair creates is never passed to the targeted tests. A refusal recorded before the test phase still lets the build run model-written tests and ask for repairs, although the build cannot commit (#1523 F-153 item 18).
3. **Item 6.** A build in `reviewing` holds no files, so a second build on the same files is dispatched against the same base.
4. **Item 7.** On the native agent's visiting route the session is seeded with localisation excerpts. The adapter's scan takes `base` from them, so `execute_approved_build`'s base check refuses every whole-file change to a localised target. `transporter_complete` changes keep CodebaseIndex-relative paths, which the write boundary and BF-904a's missing-target refusal reject.

## 2. Solution overview

- **M1 (item 2).** `execute_approved_build` gains `enforce_sealed_core: bool | None = None`; `None` reads the runtime's config, as before. The resolve route passes `sealed_core_enforced(rt)`. The dispatcher is given the flag at construction from `config.extensions.enforce_sealed_core`. When the flag is on, the globs are read once at entry from this ProbOS's own policy file. Each write site passes the block's repository-relative path, which is matched with `/` separators, `.` and doubled separators removed, and case folded on both sides. Still a warning per write; never a refusal.
- **M2 (item 4 and F-153 item 18).** `validation_errors` holds refusals only. Each path a write validated is recorded in `syntax_checked`, and its syntax is read at step 5.5 on the files as they are then. `all_changed_files` is read at the start of each attempt. A build that holds a refusal before the review runs no review, no targeted tests and no repair.
- **M3 (items 6 and 7).** `reviewing` holds a build's files. `perceive` keeps the whole files for the visiting builder: the seed and the adapter get them, and the adapter gets the mapping the seed returns. The excerpts stay the native prompt's context. `act` normalises every `transporter_complete` change.

## 3. Decisions

- **D1 (premise).** Item 6's branch clause was met by BF-904a D31; it is recorded, not rebuilt (§0).
- **D2 (slicing).** M1 item 2; M2 item 4 and F-153 item 18; M3 items 6 and 7. One broad gate and one PR for all three. M1 and M2 share `execute_approved_build`, so M2's review reads M1's changes to that function. M3 is independent; its chain test (V2) runs the executor M1 and M2 left. Ranked: (A) this order; (B) item 4 first, which defers the security-relevant review; (C) four milestones, which exceeds the three-slice batch.
- **D3 (item 2 wiring).** (A) **chosen:** a flag parameter. The route reads its runtime's config tolerantly; the dispatcher is given the flag by constructor injection; `BuildPipeline`'s runtime path is unchanged. (B) Pass the runtime from both callers: rejected. It switches on the pre-flight runner (`builder.py:3211-3222`; `startup/finalize.py:4274` sets `runtime.pre_flight_runner`) and Hebbian recording (`builder.py:3742-3748`) for those routes, and the dispatcher would have to hold the whole runtime. (C) A global config lookup: rejected (a hidden dependency).
- **D4 (item 2 matching).** (A) **chosen:** lexical normalisation of the admitted change path (`os.path.normpath`, `/` separators, `str.casefold` on the path and on the globs), with the policy read from `_PROJECT_ROOT/config/sealed_modules.yaml` only when the flag is on. Case folding gives one rule on every host: a sealed file written under another case on Windows or macOS is still the sealed file. On a case-sensitive Linux tree it can over-report a distinct `Src/...` directory, which is acceptable for a warning. (B) `realpath` relative to `work_dir`: rejected. It follows links and junctions (F-124 owns aliases), and a file that does not yet exist resolves differently per host. (C) The work tree's own policy: rejected, because a build can write `config/` (`builder_paths.py:52`) and so could switch its own observation off.
- **D5 ("observed").** One `logger.warning` on `probos.cognitive.builder` per write to a sealed path, at each of the four write sites, naming the path as written (`%r`); the build's outcome is unchanged. With the flag off: no policy read, no `is_sealed_path` call, no log. No `BuildResult` field and no event (AD-481l's). A policy that cannot be read gives no globs: that build observes nothing and its outcome is still unchanged. The loader degrades a missing file (no log), a YAML error and an OS error in the read (its own warning). `_sealed_globs` degrades whatever else the one loader call lets out, of any class but `MemoryError`: an `OSError` from the existence check, a `ValueError` such as a decoding error or an impossible date, the `OverflowError`, `KeyError`, `IndexError` and `AttributeError` PyYAML's constructors raise on corrupt scalars, a `RecursionError` from deep nesting, and any class a parser raises that no list names. One warning names the file and the exception class (Amendment A2, §17; the open set, Amendment A4, §19).
- **D6 (item 4 state).** (A) **chosen:** refusals stay in `validation_errors`; syntax is a set of paths read again at 5.5 on the current files; the error keeps its `"Syntax errors:"` lead (19 assertions in 5 test files read it), refusals first. (B) Drop a path's error when a later write of it validates: rejected. It misses changes the tests make (F6) and needs per-path bookkeeping. (C) Re-validate at the start of each attempt: rejected; still stale after the last attempt.
- **D7 (F-153 item 18, coupled).** (A) **chosen:** a refusal recorded before the review skips the review, the targeted tests and the repair loop. Item 4 makes a refusal permanent, so these steps can only run model-written code and spend model calls for a build that cannot commit. (B) Leave it: rejected. Closes the BF-904b part of F-153 item 20 too, since a write-time refusal is in the same list.
- **D8 (F-153 item 4, not taken).** `classify_build_failure`'s substring matching is a separate contract: categories feed the resolution options and the HXI. Item 4 adds no string it matches (the lead stays `"Syntax errors"`, which contains none of its five substrings). Every resolution it can offer re-runs the guarded executor, and after an incomplete cleanup only abort is taken (BF-904a D30). It stays in the register.
- **D9 (item 6).** `_FOOTPRINT_HOLDING_STATUSES = ("dispatched", "building", "reviewing")`. `queued` holds nothing (not generated yet); `merged` and `failed` are terminal. `approved` and `retrying` are not statuses of this queue (Absence Verified). `active_count` (worker concurrency) is unchanged. No race opens: `_try_dispatch` finds and marks a build with no await between (`build_dispatcher.py:123-130`), and `building` goes straight to `reviewing` (`:270-273`).
- **D10 (item 7).** (A) **chosen:** whole files to the seed and the adapter, the adapter given the mapping the seed returns (as the dispatcher does, `build_dispatcher.py:191`, `:203`); the excerpts stay the native prompt context and the Transporter's size estimate; every `transporter_complete` change normalised (for a project-relative path, including the native harness's, the normaliser returns it unchanged). (B) Skip localisation on the visiting route: rejected; the route is decided after the context is built, and the native fallback needs the excerpt. (C) Whole files on disk but excerpts in the mapping: rejected; the scan compares against, and takes `base` from, the mapping (`copilot_adapter.py:819`, `:838-848`).
- **D11 (tier).** HIGH.
- **D12 (the final syntax read, Amendment A3).** The 5.5 read runs after model-written tests, which can leave any filesystem state, so it reads only inside the work tree. (A) **chosen:** resolve, confine, then one checked open. `realpath` of the path must lie inside `realpath(work_dir)` (by `normcase`). An `lstat` must show a regular file. One open with BF-904a's `_HOOK_OPEN_FLAGS` (no final link, no blocking on a pipe), whose `fstat` must be that same regular file (`samestat`). This is the builder's existing rule: `_write_target_key` (D32) unifies spellings with `realpath`, and the write boundary follows aliases (`builder_paths.py:12`). So an alias that stays inside the tree is read, and one that leads out is refused unread, as one `Syntax errors:` line naming the path. (B) Refuse every link, junction or reparse point between the root and the leaf: rejected. It is stricter than the writes, and a new failure for an in-tree link that M1 accepts. (C) A no-follow open of the leaf with `fstat` alone: rejected. An `lstat` of the leaf follows an ancestor junction (`S_ISREG` True, measured on CPython 3.12.13), and Windows has no `O_NOFOLLOW`. (D) `security/file_access.py`'s `read_verified_file` / `pin_directory`: rejected. They pin the whole absolute chain and refuse an alias above the work tree too (`:851`, `:873`), a new failure for a work tree under a junction or `/var`, and they need read-authority roots this executor does not hold. The helpers are private to `builder.py`; the root reaches `_syntax_errors(root, paths)` from its single call. Not closed: a process the tests left running that swaps an ancestor of the resolved path into an alias after the `realpath` and before the `lstat` (F-124 on #1523).

**Disclosed effects.**
1. With `enforce_sealed_core` on, writes to sealed paths now log. The default is off (`config_models/agentic.py:135`).
2. A build with a refusal runs no review, tests or repair.
3. A build in review blocks overlapping queued builds until it is rejected; delivery refuses under BF-897.
4. The visiting prompt carries whole files.
5. Syntax errors are listed once per file, after the refusals.
6. A Python file the tests deleted, replaced with a non-regular file, or left undecodable now fails the build as syntax state, before `git add`.
7. (Amendment A3) A Python file that resolves outside the work tree at 5.5 (a link or junction the tests left above it or in its place) fails the build unread. One that resolves inside it is read. A build whose own write already went through a link out of the tree now fails there too (this repository tracks no symbolic link: `git ls-files -s` has no mode 120000).

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in this order. Focused gate per milestone, `-n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Production files | Tests | Focused gate |
|---|---|---|---|
| **M1** item 2 | `cognitive/builder.py` (7.1), `routers/build.py` (7.2), `build_dispatcher.py` (7.3), `startup/structural_services.py` (7.4) | new 7.6; update 7.5, 7.5b | `tests/test_bf904b_sealed_core_observation.py tests/test_ad481_extensions.py tests/test_bf896_executor_identity_and_blocks.py tests/test_build_dispatcher.py tests/test_bf896_dispatcher_confinement_seam.py tests/test_bf904a_failed_build_restore.py tests/test_builder_api.py tests/test_layer_boundaries.py` |
| **M2** item 4 and F-153 item 18 | `cognitive/builder.py` (7.7) | new 7.9; update 7.8 | `tests/test_bf904b_fix_loop_state.py tests/test_bf898_fix_loop_grader_protection.py tests/test_bf904a_failed_build_restore.py tests/test_bf904a_git_hardening.py tests/test_bf904a_unapplied_blocks.py tests/test_bf896_executor_identity_and_blocks.py tests/test_builder_guardrails.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_builder_agent.py tests/test_ad1344_constitution_write_refusal.py tests/test_ad1343_seam_registry.py tests/test_bf904b_sealed_core_observation.py` |
| **M3** items 6 and 7, trackers | `build_queue.py` (7.10), `cognitive/builder.py` (7.11); trackers (§8) | new 7.13; update 7.12 | `tests/test_bf904b_dispatch_and_visiting.py tests/test_build_queue.py tests/test_build_dispatcher.py tests/test_bf896_executor_identity_and_blocks.py tests/test_builder_agent.py tests/test_copilot_adapter.py tests/test_bf904b_sealed_core_observation.py tests/test_bf904b_fix_loop_state.py tests/test_ad1184_ad_ledger.py` |

If an existing test outside §7 fails only because it asserted that the tests or the review ran after a main-loop refusal, it pins F-153 item 18. Update it with an inline `BF-904b (#1585)` reason and never delete it. Stop and report any other failure.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `execute_approved_build(enforce_sealed_core=...)` | `routers/build.py` `_execute_build` (passes it); `BuildDispatcher._execute_build` (passes it); `BuildPipeline.execute_approved_build` (does not; its runtime is read); every test that calls the executor (default `None` keeps their behaviour); the signature pin `tests/test_bf896_executor_identity_and_blocks.py:701-705` (updated, 7.5b) | keyword with a default, added after `expected_git_dir`: every earlier parameter keeps its name, index and kind, so no existing positional call changes meaning; `enforce_sealed_core` is now the last parameter |
| `_check_sealed_path(change_path, sealed_globs)` | the four write sites; `tests/test_ad481_extensions.py` (updated, 7.5) | new signature |
| `sealed_core_enforced(runtime)` | the executor (no flag given); the resolve route | True only for the boolean True |
| `BuildDispatcher(enforce_sealed_core=False)` and its read-only property | `startup/structural_services.py`; `tests/test_build_dispatcher.py` and `tests/test_bf896_dispatcher_confinement_seam.py` (keyword-only default; their patched executors take `**kwargs`) | none |
| `result.error` for refusals and syntax state | `classify_build_failure` (reads `error` and `test_result`); `_execute_build`'s failure cache; 19 `startswith("Syntax errors")` assertions | lead unchanged; refusals first, then syntax, one line per file |
| skipping review, tests and repair after a refusal | `result.review_result`, `test_result`, `tests_passed`, `metadata["targeted_tests"]`, `["full_suite"]`, `["fix_loop_files"]` stay unset, as on any build whose tests did not run; `git_unsafe` stays False, so the cleanup runs git as before | the error is the refusal list |
| `has_footprint_conflict` | `BuildDispatcher._find_dispatchable` (`build_dispatcher.py:144`) | a build in review blocks overlapping queued builds |
| visiting seed and adapter mapping | `seed_session_directory`; `CopilotBuilderAdapter.execute` (prompt, scan comparison, `base`); `perceive`'s native context (`:2382-2397`) and `_should_use_transporter` size (`:2516`), both still excerpts | whole files to the visiting session |
| `act()`'s `transporter_complete` changes | `routers/build.py` `_run_build` (`BUILD_GENERATED`); the Captain's approval cache; `execute_approved_build` | project-relative paths |

## 6. Tests

All tests run on real objects: real git in `tmp_path` repositories, the real `is_sealed_path` with the real `config/sealed_modules.yaml`, the real `BuildQueue`, `BuildDispatcher`, `BuildPipeline`, `BuilderAgent` (`perceive`, `decide`, `act`) and path normaliser, and one real boot. The model and the targeted-test runner are stand-ins: they model untrusted input, and the runner's own behaviour is BF-897's.

| Id | Test | Premise asserted | Today |
|---|---|---|---|
| S1 | `test_a_write_to_a_sealed_path_is_observed_at_each_write_site[modify, create, repair-modify, repair-create]` | each write site logs one observation naming the path, and the build commits | fails (no runtime, so nothing logs) |
| S2 | `test_spellings_of_a_sealed_path_are_observed_and_others_are_not[6 ids]` | case, backslash, `.` and `//` spellings are observed; a sibling directory, an escaping path and an unsealed file are not | fails (old signature) |
| S2b | `test_a_glob_is_matched_without_regard_to_case[file, directory-itself]` | a glob written in another case still matches | fails |
| S3 | `test_with_the_flag_off_no_policy_is_read_and_nothing_is_logged[off, unset-without-runtime]` | no policy read, no match, no log | passes (guard) |
| S4 | `test_the_policy_is_this_probos_file_not_the_work_tree_or_the_working_directory` | an empty policy in the work tree, which is also the working directory, does not switch the observation off | fails |
| S5 | `test_the_resolve_route_passes_the_runtime_flag[flag-on, no-config]` | the route observes when its runtime's config is on; a runtime without config builds with no log | fails `[flag-on]` |
| S6 | `test_the_dispatcher_hands_its_flag_to_the_executor[on, default]` | the executor receives the dispatcher's flag | fails (TypeError) |
| S7 | `test_a_real_boot_wires_the_config_flag_into_the_dispatcher` | a boot with the flag on gives a dispatcher with it on | fails |
| S8 | `test_build_pipeline_still_turns_it_on_through_its_runtime` | `BuildPipeline`'s runtime config turns it on | fails (absolute path) |
| S9 | `test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits[not-utf-8, invalid-date, overflow, unknown-bool, empty-int, bad-timestamp, deep-nesting, unlisted-class]` | with the flag on, a policy the loader raises on, of any class but `MemoryError`, gives one warning naming the file and the exception class, nothing is observed, and the resolve route's build commits; each case's class is asserted (the premise that the case reaches the guard) | fails (no `_SEALED_POLICY` before M1; on the round-1 M1 candidate the route reports `BUILD_FAILURE`; on the round-2 candidate `68fb9959` `[overflow, unknown-bool, empty-int, bad-timestamp, unlisted-class]` report `BUILD_FAILURE`, Amendment A4) |
| S10 | `test_running_out_of_memory_while_loading_the_policy_still_propagates` | a `MemoryError` from the loader's parser leaves `_sealed_globs`; it is not degraded | fails before M1 (no `_sealed_globs`); passes on round-2 M1: a guard against a catch widened past `MemoryError` (Amendment A4) |
| F1 | `test_a_syntax_error_a_repair_fixes_no_longer_blocks_the_commit` | a repaired syntax error commits | fails |
| F2 | `test_a_file_a_repair_creates_is_targeted_on_the_next_attempt` | attempt 2 targets the repair's new file | fails |
| F3 | `test_a_refusal_blocks_the_commit_whatever_the_syntax_state` | a refusal blocks although every file parses | passes (guard) |
| F4 | `test_a_build_with_a_refusal_runs_no_tests_review_or_repair` | no targeted test, review or repair after a refusal | fails |
| F5 | `test_a_syntax_error_still_there_after_the_loop_blocks_the_commit[main-create, main-modify, repair]` | a syntax error still present blocks, naming the file, although the tests passed | passes (guard) |
| F6 | `test_the_syntax_state_is_read_from_the_files_the_tests_left[broken, deleted, undecodable, directory]` | what the tests left is judged | fails (`[directory]` passes on M2: a guard, Amendment A3) |
| F7 | `test_an_alias_the_tests_leave_is_refused_and_its_target_never_parsed[ancestor, leaf]` | a directory link or junction the tests leave above the created file, or a link in its place, is refused and named, and the valid text outside the work tree is never parsed | fails (the round-1 M2 candidate parses the outside text and commits); `[leaf]` skips where no file link can be made (Windows without the privilege) (Amendment A3) |
| F8 | `test_a_file_that_cannot_be_examined_after_the_tests_is_one_syntax_line[stat-fails, swapped-before-open]` | a failing examination after the tests, and a different file opened than the one examined, are each one line under `Syntax errors:` | fails (round-1 M2: the stat raises before the `try`; nothing checks the opened file) (Amendment A3) |
| D1 | `test_a_build_in_review_holds_its_files` | an overlapping build waits while one is in review; a disjoint one goes; rejection releases it | fails |
| D2 | `test_which_statuses_hold_a_builds_files[queued, dispatched, building, reviewing, merged, failed]` | the holding set is exactly dispatched, building, reviewing | fails `[reviewing]` |
| V1 | `test_the_visiting_builder_is_seeded_with_whole_files` | the adapter mapping and the session disk hold the whole file; the native context is still an excerpt | fails |
| V2 | `test_a_whole_file_change_from_the_visiting_builder_applies` | perceive, decide, act and execute: the visiting builder's whole-file change commits | fails (base refused) |
| V3 | `test_transporter_changes_get_project_relative_paths[transporter, visiting]` | act gives `src/probos/pkg/mod.py` for `pkg/mod.py`, and the executor applies it | fails (missing target refused) |

Updated pins, not new cases: 7.5 (the two `_check_sealed_path` tests, M1), 7.5b (the executor's signature pin, M1; Amendment A1), 7.8 (M2), 7.12 (M3).

## 7. The contract

### 7.1 `src/probos/cognitive/builder.py` (M1)

`Field` is not a ProbOS name (pydantic's); it appears below only in the docstring this block removes.

SEARCH:
```python
def _check_sealed_path(target_path: "Path", runtime: "ProbOSRuntime | None") -> None:
    """AD-481f: warn-only sealed-core pre-write check.

    Reads `runtime.config.extensions.enforce_sealed_core` (default False).
    When True, emits `logger.warning(...)` — never raises in v1. Hard-block
    ships at AD-481l after AD-482 RedTeam baseline establishes false-
    positive rate. Per-BuildSpec override (`core_modification` flag) is
    intentionally NOT introduced in v1 — that knob lands with AD-481l when
    the warn becomes a raise.

    `runtime.config.extensions` is guaranteed by
    `SystemConfig.extensions = Field(default_factory=ExtensionsConfig)`.
    """
    if runtime is None:
        return
    try:
        if not runtime.config.extensions.enforce_sealed_core:
            return
    except AttributeError:
        return
    from probos.extensions.sealed_core import is_sealed_path
    if is_sealed_path(target_path):
        logger.warning(
            "AD-481f: Builder writing to sealed-core path %s "
            "(enforce_sealed_core=True); v1 is observation-only — "
            "hard-block ships at AD-481l",
            target_path,
        )
```
REPLACE:
```python
#: BF-904b (#1585): the sealed-core policy this ProbOS runs under. Never the work tree's copy (a build writes
#: the work tree, config/ included, so it could rewrite its own policy) and never a path relative to the
#: process's working directory, which is not the repository.
_SEALED_POLICY = _PROJECT_ROOT / "config" / "sealed_modules.yaml"


def sealed_core_enforced(runtime: Any) -> bool:
    """BF-904b (#1585): whether *runtime*'s config turns the sealed-core observation (AD-481f) on.

    True only when ``runtime.config.extensions.enforce_sealed_core`` is the boolean True; False for None,
    for an object without that chain (a test double) and for any other value, as the AttributeError branch
    of the check this replaces did. The /api/build routes call it on their runtime: they pass no runtime to
    the executor, which would switch on the pre-flight runner and Hebbian recording for them.
    """
    try:
        return runtime.config.extensions.enforce_sealed_core is True
    except AttributeError:
        return False


def _sealed_globs() -> tuple[str, ...]:
    """BF-904b (#1585): the globs of this ProbOS's sealed-core policy; empty when it is missing or cannot be read.

    The loader degrades a missing file, a YAML error and an OS error in the read itself. Whatever else it raises
    on this file is caught here, of any class: an OS error from its existence check, a file that is not UTF-8,
    and what PyYAML's constructors and composer raise on corrupt content (an impossible date, a sexagesimal float
    too large, an unknown ``!!bool``, an empty ``!!int``, nesting past the recursion limit). That set is open:
    each constructor raises what its own code raises, and a later PyYAML can add a class. So the boundary is this
    one call, not a list (Amendment A4); the code after it handles ``str`` values only and is not guarded. One
    warning names the file and the exception class, and the observation never changes a build's outcome (D5). A
    ``MemoryError`` still propagates: the process, not the policy, has failed. Nothing is cached when the loader
    raises, so each flagged build reads the file again.
    """
    from probos.extensions.sealed_core import load_sealed_globs

    try:
        return load_sealed_globs(str(_SEALED_POLICY))
    except MemoryError:
        raise  # BF-904b A4: the process is out of memory, not the policy unreadable; the build fails as before
    except Exception as exc:  # BF-904b A4: third-party parsing of an external file; its failure set is open
        logger.warning(
            "BF-904b: the sealed policy %s cannot be read (%s); this build observes nothing",
            _SEALED_POLICY, type(exc).__name__,
        )
        return ()  # BF-904b A2: no globs, so nothing is observed and the build goes on


def _check_sealed_path(change_path: str, sealed_globs: tuple[str, ...]) -> None:
    """AD-481f: warn-only sealed-core pre-write check. BF-904b (#1585): it can fire.

    *sealed_globs* is what ``execute_approved_build`` loaded at entry: the policy's globs when
    ``enforce_sealed_core`` is on, otherwise empty, and then nothing is matched or logged. *change_path* is
    the block's repository-relative path, which BF-894's write boundary has admitted. It is matched with ``/``
    separators, ``.`` and doubled separators removed, and case folded on both sides, so a spelling the host's
    filesystem resolves to a sealed file is observed on every host. A path naming nothing inside the
    repository (absolute, or escaping with ``..``) matches no repository-relative glob; the boundary refuses
    it before this runs. One ``logger.warning`` per write; never raises. The hard block is AD-481l, after
    the AD-482 RedTeam baseline; the per-BuildSpec ``core_modification`` override lands with it.
    """
    if not sealed_globs:
        return
    rel = os.path.normpath(change_path.replace("\\", "/")).replace("\\", "/").casefold()
    from probos.extensions.sealed_core import is_sealed_path

    if is_sealed_path(rel, tuple(glob.casefold() for glob in sealed_globs)):
        logger.warning(
            "AD-481f: Builder writing to sealed-core path %r "
            "(enforce_sealed_core=True); v1 is observation-only — "
            "hard-block ships at AD-481l",
            change_path,
        )
```

SEARCH:
```python
    specialty: str = "general",
    expected_git_dir: str | None = None,
) -> BuildResult:
```
REPLACE:
```python
    specialty: str = "general",
    expected_git_dir: str | None = None,
    enforce_sealed_core: bool | None = None,
) -> BuildResult:
```

SEARCH:
```python
            at entry (before any git command or write) and again before the
            commit if *work_dir* no longer names that repository.
    """
    result = BuildResult(success=False, spec=spec)
```
REPLACE:
```python
            at entry (before any git command or write) and again before the
            commit if *work_dir* no longer names that repository.
        enforce_sealed_core: BF-904b (#1585). Whether writes to sealed-core paths
            are observed (AD-481f: a warning per write, never a refusal). None
            reads ``runtime``'s config (``BuildPipeline``); the /api/build routes
            and the dispatcher pass the flag, because they pass no runtime.
    """
    result = BuildResult(success=False, spec=spec)
```

SEARCH:
```python
    git_baseline: _GitSafetySnapshot | None = None
    tests_ran = False

    # 0a. BF-897 (#1559): refuse the checkout the runtime started from (a location
```
REPLACE:
```python
    git_baseline: _GitSafetySnapshot | None = None
    tests_ran = False
    # BF-904b (#1585): the sealed-core observation (AD-481f). The caller's flag, else the runtime's config;
    # the policy is read only when it is on, before any git command or write.
    observe_sealed = enforce_sealed_core if enforce_sealed_core is not None else sealed_core_enforced(runtime)
    sealed_globs = _sealed_globs() if observe_sealed is True else ()

    # 0a. BF-897 (#1559): refuse the checkout the runtime started from (a location
```

SEARCH:
```python
                if modified != original:
                    _check_sealed_path(path, runtime)
```
REPLACE:
```python
                if modified != original:
                    _check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's modify
```

SEARCH:
```python
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(path, runtime)
            pre_existing = path.exists() and change["path"] not in written
            if pre_existing and _first_found(work_dir, change["path"], found_keys):  # BF-904a A4 (D32): once per file, a create over it too
```
REPLACE:
```python
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's create
            pre_existing = path.exists() and change["path"] not in written
            if pre_existing and _first_found(work_dir, change["path"], found_keys):  # BF-904a A4 (D32): once per file, a create over it too
```

SEARCH:
```python
                                if mod != original:
                                    _check_sealed_path(path, runtime)
```
REPLACE:
```python
                                if mod != original:
                                    _check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's modify
```

SEARCH:
```python
                                path.parent.mkdir(parents=True, exist_ok=True)
                                _check_sealed_path(path, runtime)
```
REPLACE:
```python
                                path.parent.mkdir(parents=True, exist_ok=True)
                                _check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's create
```

### 7.2 `src/probos/routers/build.py` (M1)

SEARCH:
```python
    from probos.cognitive.builder import execute_approved_build

    try:
        rt.emit_event(EventType.BUILD_PROGRESS, {
```
REPLACE:
```python
    from probos.cognitive.builder import execute_approved_build, sealed_core_enforced

    try:
        rt.emit_event(EventType.BUILD_PROGRESS, {
```

SEARCH:
```python
            llm_client=getattr(rt, "llm_client", None),
            escalation_hook=None,
        )
```
REPLACE:
```python
            llm_client=getattr(rt, "llm_client", None),
            escalation_hook=None,
            enforce_sealed_core=sealed_core_enforced(rt),  # BF-904b (#1585): the runtime's flag; no runtime is passed
        )
```

### 7.3 `src/probos/build_dispatcher.py` (M1)

SEARCH:
```python
        run_tests: bool = True,
        on_build_complete: Callable[[QueuedBuild], Awaitable[None]] | None = None,
    ) -> None:
```
REPLACE:
```python
        run_tests: bool = True,
        on_build_complete: Callable[[QueuedBuild], Awaitable[None]] | None = None,
        enforce_sealed_core: bool = False,
    ) -> None:
```

SEARCH:
```python
        self._on_build_complete = on_build_complete
        self._task: asyncio.Task[None] | None = None
```
REPLACE:
```python
        self._on_build_complete = on_build_complete
        # BF-904b (#1585): AD-481f's sealed-core observation for the builds this dispatcher runs, given at
        # construction from config.extensions.enforce_sealed_core (startup/structural_services.py).
        self._enforce_sealed_core = enforce_sealed_core
        self._task: asyncio.Task[None] | None = None
```

SEARCH:
```python
    @property
    def active_builds(self) -> list[str]:
        """Build IDs currently being executed."""
        return list(self._active_tasks.keys())
```
REPLACE:
```python
    @property
    def active_builds(self) -> list[str]:
        """Build IDs currently being executed."""
        return list(self._active_tasks.keys())

    @property
    def enforce_sealed_core(self) -> bool:
        """BF-904b (#1585): whether the builds this dispatcher runs observe writes to sealed-core paths."""
        return self._enforce_sealed_core
```

SEARCH:
```python
                builder_source="visiting",
                expected_git_dir=expected_git_dir,
            )
```
REPLACE:
```python
                builder_source="visiting",
                expected_git_dir=expected_git_dir,
                enforce_sealed_core=self._enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation
            )
```

### 7.4 `src/probos/startup/structural_services.py` (M1)

SEARCH:
```python
    build_dispatcher = BuildDispatcher(
        queue=build_queue,
        worktree_mgr=_worktree_mgr,
        on_build_complete=on_build_complete_fn,
    )
```
REPLACE:
```python
    build_dispatcher = BuildDispatcher(
        queue=build_queue,
        worktree_mgr=_worktree_mgr,
        on_build_complete=on_build_complete_fn,
        enforce_sealed_core=config.extensions.enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation, off by default
    )
```

### 7.5 `tests/test_ad481_extensions.py` (M1: the two tests pinned the old signature)

The old tests' runtime double was a `SimpleNamespace` chain; it is removed with its import, and the runtime read is covered by S5 and S8.

SEARCH:
```python
from pathlib import Path
from types import SimpleNamespace

import pytest
```
REPLACE:
```python
from pathlib import Path

import pytest
```

SEARCH:
```python
    def test_check_sealed_path_warns_when_enforce_true(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                extensions=SimpleNamespace(enforce_sealed_core=True)
            )
        )
        # Force a sealed glob that matches our test path — patch the helper to
        # bypass the project sealed_modules.yaml lookup by providing the glob
        # via the underlying is_sealed_path. We use the real function with a
        # path we know is in the default sealed list.
        load_sealed_globs.cache_clear()
        with caplog.at_level(logging.WARNING):
            _check_sealed_path(Path("src/probos/substrate/agent.py"), runtime)
        assert any("sealed-core" in r.message for r in caplog.records)

    def test_check_sealed_path_silent_when_enforce_false(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                extensions=SimpleNamespace(enforce_sealed_core=False)
            )
        )
        with caplog.at_level(logging.WARNING):
            _check_sealed_path(Path("src/probos/substrate/agent.py"), runtime)
        assert not any("sealed-core" in r.message for r in caplog.records)
```
REPLACE:
```python
    def test_check_sealed_path_warns_when_enforce_true(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path, _sealed_globs
        # BF-904b (#1585): the check now takes the change's repository-relative path and the globs its caller
        # loaded because enforce_sealed_core is on. It used to take the runtime, and production handed it an
        # absolute path that no glob matched, so this test passed while the check never fired.
        load_sealed_globs.cache_clear()
        with caplog.at_level(logging.WARNING):
            _check_sealed_path("src/probos/substrate/agent.py", _sealed_globs())
        assert any("sealed-core" in r.message for r in caplog.records)

    def test_check_sealed_path_silent_when_enforce_false(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path
        # BF-904b (#1585): with enforce_sealed_core off the caller loads no globs, so the check is given none.
        with caplog.at_level(logging.WARNING):
            _check_sealed_path("src/probos/substrate/agent.py", ())
        assert not any("sealed-core" in r.message for r in caplog.records)
```

### 7.5b `tests/test_bf896_executor_identity_and_blocks.py` (M1: the test pinned expected_git_dir as the last parameter)

7.1 adds `enforce_sealed_core` after `expected_git_dir`. The test's purpose (no existing positional call changes meaning) still holds and is now asserted directly; only its "last" clause was obsolete. Amendment A1 (§16).

SEARCH:
```python
def test_expected_git_dir_is_an_optional_last_parameter() -> None:
    parameters = list(inspect.signature(execute_approved_build).parameters.values())
    assert parameters[-1].name == "expected_git_dir", "last, so no existing positional call changes meaning"
    assert parameters[-1].default is None
    assert all(p.default is not inspect.Parameter.empty for p in parameters[3:]), "everything after work_dir is optional"
```
REPLACE:
```python
def test_expected_git_dir_keeps_its_position_and_only_optional_parameters_follow_it() -> None:
    # BF-904b (#1585): this test asserted that expected_git_dir is the last parameter, and BF-904b adds
    # enforce_sealed_core after it. It now asserts the property it named: every parameter the signature had keeps
    # its name, index and kind, so no existing positional call changes meaning, and the new flag follows them.
    parameters = list(inspect.signature(execute_approved_build).parameters.values())
    before = [
        "file_changes", "spec", "work_dir", "run_tests", "max_fix_attempts", "llm_client",
        "escalation_hook", "builder_source", "runtime", "specialty", "expected_git_dir",
    ]
    kept = parameters[: len(before)]
    assert [p.name for p in kept] == before, "no existing positional call changes meaning"
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in kept), "each can still be passed by position"
    assert kept[-1].default is None
    assert "enforce_sealed_core" in [p.name for p in parameters[len(before) :]], "BF-904b's flag follows expected_git_dir"
    assert all(p.default is not inspect.Parameter.empty for p in parameters[3:]), "everything after work_dir is optional"
```

### 7.6 New file: `tests/test_bf904b_sealed_core_observation.py` (M1)

```python
"""BF-904b (#1585), milestone M1: the sealed-core observation (AD-481f, warn-only) can fire.

Before M1 ``_check_sealed_path`` returned at once without a runtime, and neither production caller of
``execute_approved_build`` passed one (the resolve route's ``_execute_build``, ``BuildDispatcher._execute_build``).
Given a runtime (``BuildPipeline``), it handed ``is_sealed_path`` the absolute ``Path(work_dir) / path``, which no
repository-relative glob matches. M1 passes the flag, reads this ProbOS's own policy file only when it is on, and
matches the change path repository-relative, with ``/`` separators and case folded. Observation only: no build is
refused for it (AD-481l is the hard block).

Rules: real git in repositories under ``tmp_path`` (helpers copied from the BF-904a tests); the real
``is_sealed_path`` with the real ``config/sealed_modules.yaml``; the real ``BuildDispatcher``, ``BuildPipeline`` and
a real boot. Every ``GIT_*`` name is removed from the environment and the policy cache is cleared around each test.
No sleeps; every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace as _SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.build_dispatcher import BuildDispatcher
from probos.build_pipeline import BuildPipeline
from probos.build_queue import BuildQueue
from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.events import EventType
from probos.extensions import sealed_core as sealed_core_module
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeInfo, WorktreeManager

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
SEALED = "src/probos/substrate/agent.py"
SEALED_NEW = "src/probos/substrate/fresh.py"
SEED = {TARGET: "x = 1\n", SEALED: "a = 1\n"}
BUILDER_LOGGER = "probos.cognitive.builder"
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    sealed_core_module.load_sealed_globs.cache_clear()
    yield
    sealed_core_module.load_sealed_globs.cache_clear()


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf904b@example.invalid"),
        ("config", "user.name", "BF904b Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _spec(title: str = "bf904b probe") -> BuildSpec:
    return BuildSpec(title=title, description="")


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


def _modify_block(path: str, search: str, replace: str) -> str:
    return f"===MODIFY: {path}===\n===SEARCH===\n{search}\n===REPLACE===\n{replace}\n===END REPLACE===\n===END MODIFY===\n"


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


async def _build(work_dir: Path, changes: list[dict[str, Any]], **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await _bounded(execute_approved_build(changes, _spec(), str(work_dir), **kwargs))


class _Targeted:
    """Stands in for ``_run_targeted_tests``: answers *passes* in order and records each call's changed files."""

    def __init__(self, passes: list[bool]) -> None:
        self._passes = list(passes)
        self.calls: list[list[str]] = []

    async def __call__(self, work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        self.calls.append(list(changed_files))
        passed = self._passes.pop(0)
        return passed, ("1 passed" if passed else "1 failed"), ["tests/test_a.py"]


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too)."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=_SimpleNamespace(content=reply))


class _Runtime:
    """What the resolve route and ``BuildPipeline`` read from a runtime here: ``emit_event``, ``llm_client`` and,
    when given, ``config``. No ``pre_flight_runner`` and no ``hebbian_router``."""

    def __init__(self, config: SystemConfig | None = None) -> None:
        self.emit_event = MagicMock()
        self.llm_client = None
        if config is not None:
            self.config = config


def _config(enforce: bool) -> SystemConfig:
    config = SystemConfig()
    config.extensions.enforce_sealed_core = enforce
    return config


def _sealed_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == BUILDER_LOGGER and "sealed-core" in r.getMessage()]


def _route_modules() -> tuple[Any, Any]:
    """``(probos.api, probos.routers.build)``. The second takes its failure cache from the first, so it loads first."""
    import probos.api as api_module
    from probos.routers import build as build_router

    return api_module, build_router


# S1
@needs_git
@pytest.mark.parametrize("site", ["modify", "create", "repair-modify", "repair-create"])
async def test_a_write_to_a_sealed_path_is_observed_at_each_write_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, site: str,
) -> None:
    """Each of the four write sites logs one observation naming the path, and the build still commits."""
    repo = _init_repo(tmp_path / "repo", SEED)
    kwargs: dict[str, Any] = {"enforce_sealed_core": True}
    if site == "modify":
        changes, written = [_modify(SEALED, "a = 1", "a = 2")], SEALED
    elif site == "create":
        changes, written = [_create(SEALED_NEW, "z = 1\n")], SEALED_NEW
    else:
        changes = [_modify(TARGET, "x = 1", "x = 2")]
        if site == "repair-modify":
            written, reply = SEALED, _modify_block(SEALED, "a = 1", "a = 3")
        else:
            written, reply = SEALED_NEW, f"===FILE: {SEALED_NEW}===\nz = 1\n===END FILE===\n"
        monkeypatch.setattr(builder_module, "_run_targeted_tests", _Targeted([False, True]))
        kwargs.update(run_tests=True, llm_client=_FakeModel(reply))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, changes, **kwargs)
    assert result.success and result.commit_hash, f"premise: an observation never blocks the build: {result.error}"
    records = _sealed_records(caplog)
    assert len(records) == 1 and repr(written) in records[0], records


# S2
@pytest.mark.parametrize(
    ("spelling", "observed"),
    [
        ("src/Probos/SUBSTRATE/agent.py", True),
        ("src\\probos\\substrate\\agent.py", True),
        ("src/probos/./substrate//agent.py", True),
        ("src/probos/substrate_extra/agent.py", False),
        ("../src/probos/substrate/agent.py", False),
        ("docs/notes.md", False),
    ],
    ids=["mixed-case", "backslashes", "dot-and-double-slash", "sibling-directory", "escaping", "unsealed"],
)
def test_spellings_of_a_sealed_path_are_observed_and_others_are_not(
    caplog: pytest.LogCaptureFixture, spelling: str, observed: bool,
) -> None:
    globs = builder_module._sealed_globs()
    assert "src/probos/substrate/**" in globs, "premise: this ProbOS's policy seals the substrate"
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        builder_module._check_sealed_path(spelling, globs)
    assert bool(_sealed_records(caplog)) is observed


# S2b
@pytest.mark.parametrize("spelling", ["src/probos/substrate/agent.py", "src/probos/substrate"], ids=["file", "directory-itself"])
def test_a_glob_is_matched_without_regard_to_case(caplog: pytest.LogCaptureFixture, spelling: str) -> None:
    """``directory-itself`` reaches only ``is_sealed_path``'s prefix test, which compares case-sensitively on every
    host, so it shows the globs are folded even where ``fnmatch`` already ignores case (Windows)."""
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        builder_module._check_sealed_path(spelling, ("SRC/Probos/Substrate/**",))
    assert len(_sealed_records(caplog)) == 1


# S3
@needs_git
@pytest.mark.parametrize("flag", ["off", "unset-without-runtime"])
async def test_with_the_flag_off_no_policy_is_read_and_nothing_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, flag: str,
) -> None:
    loads: list[int] = []
    matches: list[str] = []
    real_globs = builder_module._sealed_globs
    real_match = sealed_core_module.is_sealed_path
    monkeypatch.setattr(builder_module, "_sealed_globs", lambda: loads.append(1) or real_globs())
    monkeypatch.setattr(
        sealed_core_module, "is_sealed_path", lambda path, globs=None: matches.append(str(path)) or real_match(path, globs),
    )
    repo = _init_repo(tmp_path / "repo", SEED)
    kwargs: dict[str, Any] = {"enforce_sealed_core": False} if flag == "off" else {}
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, [_modify(SEALED, "a = 1", "a = 2")], **kwargs)
    assert result.success and result.commit_hash, result.error
    assert loads == [], "no policy is read with the flag off"
    assert matches == [], "and nothing is matched"
    assert _sealed_records(caplog) == []


# S4
@needs_git
async def test_the_policy_is_this_probos_file_not_the_work_tree_or_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A build writes the work tree, config/ included, so a policy there (here an empty one) must not switch the
    observation off; and the process's working directory is not the repository."""
    repo = _init_repo(tmp_path / "repo", {**SEED, "config/sealed_modules.yaml": "sealed_globs: []\n"})
    monkeypatch.chdir(repo)  # a policy read relative to the working directory reads the empty file above
    assert builder_module._SEALED_POLICY.is_file(), "premise: this ProbOS's policy file exists"
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, [_modify(SEALED, "a = 1", "a = 2")], enforce_sealed_core=True)
    assert result.success and result.commit_hash, result.error
    assert len(_sealed_records(caplog)) == 1


# S5
@needs_git
@pytest.mark.parametrize("runtime_kind", ["flag-on", "no-config"])
async def test_the_resolve_route_passes_the_runtime_flag(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, runtime_kind: str,
) -> None:
    _api_module, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo", SEED)
    rt = _Runtime(_config(True)) if runtime_kind == "flag-on" else _Runtime()
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        await _bounded(build_router._execute_build(
            "bf904b-s5", [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), rt, run_tests=False,
        ))
    kinds = [call.args[0] for call in rt.emit_event.call_args_list]
    assert EventType.BUILD_SUCCESS in kinds, f"premise: the build ran and committed: {kinds}"
    assert len(_sealed_records(caplog)) == (1 if runtime_kind == "flag-on" else 0)


# S6
@pytest.mark.parametrize("flag", [True, False], ids=["on", "default"])
async def test_the_dispatcher_hands_its_flag_to_the_executor(flag: bool) -> None:
    queue = BuildQueue()
    build = queue.enqueue(BuildSpec(title="bf904b dispatch", description="d", target_files=[TARGET]))
    queue.update_status(build.id, "dispatched")
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.create = AsyncMock(return_value=WorktreeInfo(path="/tmp/wt", branch=f"builder-{build.id[:8]}", build_id=build.id, created_at=0.0))
    generated = MagicMock()
    generated.success = True
    generated.file_blocks = [{"path": TARGET, "mode": "create", "content": "x = 2\n", "base": ""}]
    generated.error = ""
    adapter = MagicMock(spec=CopilotBuilderAdapter)
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    adapter.execute = AsyncMock(return_value=generated)
    stopped = BuildResult(success=False, spec=build.spec, error="bf904b: stop after the executor")
    kwargs: dict[str, Any] = {"enforce_sealed_core": True} if flag else {}
    with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
         patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=adapter) as adapter_cls, \
         patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value="/tmp/wt/.git"), \
         patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
        adapter_cls.is_available.return_value = True
        dispatcher = BuildDispatcher(queue=queue, worktree_mgr=worktrees, **kwargs)
        await _bounded(dispatcher._execute_build(build))
    assert executor.await_args is not None, "premise: the dispatcher reached the executor"
    assert executor.await_args.kwargs["enforce_sealed_core"] is flag
    assert dispatcher.enforce_sealed_core is flag


# S7
async def test_a_real_boot_wires_the_config_flag_into_the_dispatcher(tmp_path: Path) -> None:
    """``init_structural_services`` builds the one dispatcher, and nothing else passes it the flag."""
    config = _config(True)
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await _bounded(runtime.start(), 600)
    try:
        assert runtime.build_dispatcher is not None, "premise: the boot started the build dispatcher"
        assert runtime.build_dispatcher.enforce_sealed_core is True
    finally:
        await _bounded(runtime.stop(), 600)


# S8
@needs_git
async def test_build_pipeline_still_turns_it_on_through_its_runtime(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    pipeline = BuildPipeline(runtime=_Runtime(_config(True)))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _bounded(pipeline.execute_approved_build(
            [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), run_tests=False,
        ))
    assert result.success and result.commit_hash, result.error
    assert len(_sealed_records(caplog)) == 1


# S9 (Amendment A2; the corrupt scalars and the unlisted class, Amendment A4)
class _UnlistedParserFault(Exception):
    """A class no list names: what a parser raises on corrupt content is an open set (Amendment A4)."""


_OutOfMemory = MemoryError  # aliased: the phantom-API precheck reads a capitalised call as a ProbOS name
_POLICY_HEAD = b"sealed_globs:\n  - src/probos/substrate/**\n"
_UNREADABLE = [  # (id, policy bytes, the class the loader lets out); each real case executed on PyYAML 6.0.3
    ("not-utf-8", b"sealed_globs:\n  - \xff\xfe/**\n", "UnicodeDecodeError"),
    ("invalid-date", _POLICY_HEAD + b"reviewed: 2026-13-45\n", "ValueError"),
    ("overflow", _POLICY_HEAD + b"reviewed: 1" + b":0" * 179 + b".0\n", "OverflowError"),
    ("unknown-bool", _POLICY_HEAD + b"reviewed: !!bool neither\n", "KeyError"),
    ("empty-int", _POLICY_HEAD + b'reviewed: !!int ""\n', "IndexError"),
    ("bad-timestamp", _POLICY_HEAD + b"reviewed: !!timestamp never\n", "AttributeError"),
    ("deep-nesting", b"", "RecursionError"),  # sized in the test from the recursion limit
    ("unlisted-class", _POLICY_HEAD, "_UnlistedParserFault"),  # a valid file; the loader's parser is replaced
]


def _parser_raising(fault: type[BaseException]) -> Any:
    """The loader's ``yaml``, with ``safe_load`` replaced by one that raises *fault*; its ``YAMLError`` is kept."""

    def _safe_load(stream: Any) -> Any:
        raise fault("injected")

    return _SimpleNamespace(safe_load=_safe_load, YAMLError=sealed_core_module.yaml.YAMLError)


@needs_git
@pytest.mark.parametrize(("kind", "text", "raised"), _UNREADABLE, ids=[case[0] for case in _UNREADABLE])
async def test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, kind: str, text: bytes,
    raised: str,
) -> None:
    """The loader degrades a missing file, a YAML error and an OS error itself. Whatever else it raises on the file,
    of any class but ``MemoryError``, ``_sealed_globs`` catches (Amendment A4): a file that is not UTF-8, the classes
    PyYAML's constructors raise on corrupt scalars, nesting past the recursion limit, and a class no list names. With
    the flag on, one warning names the file and the exception class, nothing is observed, and the resolve route's
    build still commits (D5). A scratch policy is substituted; the shipped one loads. The class assertion is the
    premise: a case a later PyYAML turns into a ``YAMLError`` fails here, since the loader's own warning is not this."""
    if kind == "deep-nesting":  # the composer recurses twice per level, so this depth passes the limit whatever it is
        depth = sys.getrecursionlimit()
        text = ("sealed_globs: " + "[" * depth + "]" * depth + "\n").encode("utf-8")
    elif kind == "unlisted-class":
        monkeypatch.setattr(sealed_core_module, "yaml", _parser_raising(_UnlistedParserFault))
    policy = tmp_path / "policy" / "sealed_modules.yaml"
    policy.parent.mkdir()
    policy.write_bytes(text)
    monkeypatch.setattr(builder_module, "_SEALED_POLICY", policy)
    _api_module, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo", SEED)
    rt = _Runtime(_config(True))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        await _bounded(build_router._execute_build(
            "bf904b-s9", [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), rt, run_tests=False,
        ))
    kinds = [call.args[0] for call in rt.emit_event.call_args_list]
    assert EventType.BUILD_SUCCESS in kinds and EventType.BUILD_FAILURE not in kinds, f"the policy changed the build: {kinds}"
    degraded = [r.getMessage() for r in caplog.records if r.name == BUILDER_LOGGER and "sealed policy" in r.getMessage()]
    assert len(degraded) == 1 and str(policy) in degraded[0], degraded
    assert f"({raised})" in degraded[0], degraded
    assert _sealed_records(caplog) == [], "no globs, so the sealed write is not observed"


# S10 (Amendment A4)
def test_running_out_of_memory_while_loading_the_policy_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MemoryError`` is the process failing, not the policy: ``_sealed_globs`` lets it out, as before A4, and the
    route's own handler fails the build. The shipped policy is read; only the loader's parser is replaced."""
    assert builder_module._SEALED_POLICY.is_file(), "premise: the loader reaches its parser"
    monkeypatch.setattr(sealed_core_module, "yaml", _parser_raising(_OutOfMemory))
    with pytest.raises(_OutOfMemory):
        builder_module._sealed_globs()
```

### 7.7 `src/probos/cognitive/builder.py` (M2, applied after 7.1)

SEARCH:
```python
def _fix_loop_changed(path: Path, before: bytes | None) -> bool:
    """BF-898: whether a repair block left *path* holding other bytes than *before* (None: absent)."""
    try:
        return path.is_file() and path.read_bytes() != before
    except OSError:
        return True  # cannot be read back, so it cannot be shown unchanged
```
REPLACE:
```python
def _fix_loop_changed(path: Path, before: bytes | None) -> bool:
    """BF-898: whether a repair block left *path* holding other bytes than *before* (None: absent)."""
    try:
        return path.is_file() and path.read_bytes() != before
    except OSError:
        return True  # cannot be read back, so it cannot be shown unchanged


class _SyntaxReadRefused(Exception):
    """BF-904b A3 (#1585): the final syntax read will not read a path; the message says why."""


def _syntax_read_opener(name: str, flags: int) -> int:
    """BF-904b A3: the one open of the final syntax read, as BF-904a's hooks read opens (``_HOOK_OPEN_FLAGS``).

    Never a final link, never blocking on a pipe; *flags*, the text layer's, are not used.
    """
    return os.open(name, _HOOK_OPEN_FLAGS)


def _work_tree_text(root: Path, path: Path) -> str:
    """BF-904b A3 (#1585): the text of *path*, read only if it is a regular file inside the work tree *root*.

    ``realpath`` follows every symbolic link, junction and other name-surrogate reparse point on the way, the
    last name included, so an alias the tests left is followed to where it leads; that must lie inside *root*'s
    own resolved form (by ``normcase``), or the path is refused unread. An alias that stays inside the tree is
    read, as the write before it followed it (F-124 owns aliases). A path that is gone or not a regular file by
    ``lstat`` is refused before any open. The one open neither follows a final link nor blocks on a pipe, and its
    handle must be that same regular file (``samestat``). Strict UTF-8 with universal newlines, as ``read_text``.
    """
    real = os.path.realpath(path)
    if not Path(os.path.normcase(real)).is_relative_to(os.path.normcase(os.path.realpath(root))):
        raise _SyntaxReadRefused("resolves outside the work tree")
    try:
        info = os.lstat(real)
    except (FileNotFoundError, NotADirectoryError):
        raise _SyntaxReadRefused("is no longer a regular file") from None
    if not stat.S_ISREG(info.st_mode):
        raise _SyntaxReadRefused("is no longer a regular file")
    with open(real, encoding="utf-8", opener=_syntax_read_opener) as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, info):
            raise _SyntaxReadRefused("changed while it was read")
        return stream.read()


def _python_syntax_error(path: Path, text: str) -> str | None:
    """BF-904b A3 (#1585): *text*, read from *path*, parsed as ``_validate_python`` parses; the error line, or None."""
    try:
        ast.parse(text, filename=str(path))
        return None
    except SyntaxError as exc:
        return f"{path}: line {exc.lineno}: {exc.msg}"


def _syntax_errors(root: Path, paths: list[Path]) -> list[str]:
    """BF-904b (#1585): the syntax state of *paths* as they are now, one line per file that fails.

    Read at the commit decision, after any repair and after the tests, which run model-written code and can
    leave any filesystem state. A3: each Python file is read through ``_work_tree_text``, so one that resolves
    outside the work tree *root*, is gone, is not a regular file or changed while it was read is refused unread;
    one that cannot be read or decoded, or does not parse, blocks the commit. Every examination is inside the
    ``try``: ``OSError`` and ``ValueError`` become a line; anything else (``RecursionError``, ``MemoryError``)
    reaches the executor's ``except``. Only ``.py`` files are judged, as in ``_validate_python``.
    """
    errors: list[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        try:
            message = _python_syntax_error(path, _work_tree_text(root, path))
        except _SyntaxReadRefused as exc:
            message = f"{path}: {exc}; refused"
        except (OSError, ValueError) as exc:
            message = f"{path}: could not be read for the syntax check ({type(exc).__name__}); refused"
        if message is not None:
            errors.append(message)
    return errors
```

SEARCH:
```python
    validation_errors: list[str] = []
    # BF-904a (#1585): the bytes of every file that existed before this build, saved before its
```
REPLACE:
```python
    # BF-904b (#1585): refusals only, and permanent: no later step can lift one.
    validation_errors: list[str] = []
    # BF-904b (#1585): every path a write validated, in order. Syntax is state: it is read again on the files as
    # they are at the commit decision (5.5), so an error a repair fixed no longer blocks the commit.
    syntax_checked: dict[Path, None] = {}
    # BF-904a (#1585): the bytes of every file that existed before this build, saved before its
```

SEARCH:
```python
                # Validate Python files after modify
                err = _validate_python(path)
                if err:
                    validation_errors.append(err)

                continue
```
REPLACE:
```python
                # Validate Python files after modify (BF-904b: read at 5.5, on the file as it is then)
                syntax_checked[path] = None  # BF-904b: a main-loop modify, read again at 5.5

                continue
```

SEARCH:
```python
            # Validate Python files after create
            err = _validate_python(path)
            if err:
                validation_errors.append(err)
```
REPLACE:
```python
            # Validate Python files after create (BF-904b: read at 5.5, on the file as it is then)
            syntax_checked[path] = None  # BF-904b: a main-loop create, read again at 5.5
```

SEARCH:
```python
        # 4c. Code review (AD-341)
        if llm_client and (written or modified_files):
```
REPLACE:
```python
        # 4c. Code review (AD-341). BF-904b (#1585): not after a refusal, which nothing later can lift.
        if llm_client and (written or modified_files) and not validation_errors:
```

SEARCH:
```python
        # 5. Run tests with fix loop (AD-314, AD-344)
        if run_tests and (written or modified_files):
```
REPLACE:
```python
        # 5. Run tests with fix loop (AD-314, AD-344). BF-904b (#1585): a build that already holds a refusal
        # cannot commit, so it runs no model-written code and asks for no repair (#1523 F-153 item 18).
        if run_tests and (written or modified_files) and not validation_errors:
```

SEARCH:
```python
            all_changes = list(file_changes)  # track for fix prompt
            all_changed_files = written + modified_files
            fix_loop_files: list[str] = []  # BF-898: the paths the fix loop changed

            for attempt in range(1 + max_fix_attempts):
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
```
REPLACE:
```python
            all_changes = list(file_changes)  # track for fix prompt
            fix_loop_files: list[str] = []  # BF-898: the paths the fix loop changed

            for attempt in range(1 + max_fix_attempts):
                # BF-904b (#1585): read at the start of each attempt, so a file an earlier repair created is targeted.
                all_changed_files = written + modified_files
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
```

SEARCH:
```python
                            err = _validate_python(path)
                            if err:
                                validation_errors.append(err)
                        finally:
```
REPLACE:
```python
                            syntax_checked[path] = None  # BF-904b: a repair's file, read again at 5.5
                        finally:
```

SEARCH:
```python
        # 5.5. Block commit if validation errors (syntax errors) exist
        if identity_lost:
```
REPLACE:
```python
        # 5.5. Block commit if validation errors (syntax errors) exist. BF-904b (#1585): the refusals stand;
        # syntax is read now, on the files as the build and its tests left them.
        # BF-904b A3: only inside the work tree; an alias the tests left that leads out of it is refused unread.
        syntax_errors = _syntax_errors(Path(work_dir), list(syntax_checked))
        if identity_lost:
```

SEARCH:
```python
        elif validation_errors:
            result.error = "Syntax errors:\n" + "\n".join(validation_errors)
            result.success = False
```
REPLACE:
```python
        elif validation_errors or syntax_errors:
            # BF-904b: the lead is unchanged (the resolve route and the tests read it); refusals first.
            result.error = "Syntax errors:\n" + "\n".join(validation_errors + syntax_errors)
            result.success = False
```

### 7.8 `tests/test_bf898_fix_loop_grader_protection.py` (M2: the test pinned "syntax is checked after each write")

`RecursionError` is not one of the two classes `_syntax_errors` catches, so the build still ends with that error. Amendment A3: the read is `_work_tree_text` and the parse `_python_syntax_error(path, text)`, so the test raises from the parse; `_validate_python` keeps its premise use.

SEARCH:
```python
    calls: list[Path] = []

    def validate_then_raise(path: Path) -> str | None:
        calls.append(path)
        if len(calls) == 1:
            return real_validate(path)  # the approved write's validation
        raise RecursionError("maximum recursion depth exceeded during compilation")

    monkeypatch.setattr(builder_module, "_validate_python", validate_then_raise)

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert len(calls) == 2, "premise: the second validation is the repair's, and it raised"
```
REPLACE:
```python
    calls: list[Path] = []

    def parse_then_raise(path: Path, text: str) -> str | None:
        calls.append(path)
        # RecursionError is not an OSError or a ValueError, so the syntax read does not turn it into a line.
        raise RecursionError("maximum recursion depth exceeded during compilation")

    # BF-904b A3: the read after the loop reads the file inside the work tree and hands its text to this parse.
    monkeypatch.setattr(builder_module, "_python_syntax_error", parse_then_raise)

    # BF-904b (#1585): syntax is no longer checked after each write; it is read once, after the loop, on the
    # files as they are (5.5). So the validation that raises is that read, after the repair wrote foo.py, and
    # one repair attempt keeps fix_attempts and the repair prompts at one, as before.
    result = await _gated_build(build_tree, llm, max_fix_attempts=1)

    assert len(calls) == 1, "premise: the one validation is the read after the loop, and it raised"
```

### 7.9 New file: `tests/test_bf904b_fix_loop_state.py` (M2)

```python
"""BF-904b (#1585), milestone M2: refusals are permanent, syntax is state, and a refused build runs nothing.

Before M2 one list held both: every refusal and every syntax error, recorded when each file was written, so a
syntax error a repair fixed still blocked the commit; the files the targeted tests ran on were fixed before the
first attempt, so a repair's new file was never targeted; and a build holding a refusal still ran its review, its
model-written tests and its repairs (#1523 F-153 item 18). M2 keeps refusals in ``validation_errors``, reads the
syntax of every written file at the commit decision on the files as they are then, reads the changed files at each
attempt, and skips the review, the tests and the repairs after a refusal.

Rules: real git in repositories under ``tmp_path`` (helpers copied from the BF-904a tests). The model and the
targeted-test runner are stand-ins: the model's text is untrusted input and the runner is BF-897's. No sleeps;
every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace as _SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
BAD = "src/probos/bad.py"
SEED = {TARGET: "x = 1\n", OTHER: "y = 1\n"}
BROKEN = "def broken(:\n"
REFUSED = "../outside.py"
OUTSIDE_TEXT = "external = 1\n"  # A3: valid Python outside the work tree, which the final read must never parse
_Denied = PermissionError  # A3: the injected examination failure's class, aliased like the doubles' names
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf904b@example.invalid"),
        ("config", "user.name", "BF904b Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout.replace("\r\n", "\n")


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


async def _build(work_dir: Path, changes: list[dict[str, Any]], **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await _bounded(execute_approved_build(changes, BuildSpec(title="bf904b fix loop", description=""), str(work_dir), **kwargs))


class _Targeted:
    """Stands in for ``_run_targeted_tests``: answers *passes* in order and records each call's changed files."""

    def __init__(self, passes: list[bool]) -> None:
        self._passes = list(passes)
        self.calls: list[list[str]] = []

    async def __call__(self, work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        self.calls.append(list(changed_files))
        passed = self._passes.pop(0)
        return passed, ("1 passed" if passed else "1 failed"), ["tests/test_a.py"]


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too); it keeps every request."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=_SimpleNamespace(content=reply))

    def fix_prompts(self) -> list[str]:
        prompts = [call.args[0].prompt for call in self.complete.await_args_list]
        return [prompt for prompt in prompts if "Test Fix Required" in prompt]


# F1
async def test_a_syntax_error_a_repair_fixes_no_longer_blocks_the_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {BAD}===\nok = 1\n===END FILE===\n")
    result = await _build(repo, [_create(BAD, BROKEN)], run_tests=True, llm_client=model)
    assert result.fix_attempts == 1 and len(model.fix_prompts()) == 1, "premise: the first write failed and one repair ran"
    assert len(targeted.calls) == 2 and result.tests_passed is True, "premise: the tests passed after the repair"
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, BAD) == "ok = 1\n"


# F2
async def test_a_file_a_repair_creates_is_targeted_on_the_next_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {NEW}===\nok = 1\n===END FILE===\n")
    result = await _build(repo, [_modify(TARGET, "x = 1", "x = 2")], run_tests=True, llm_client=model)
    assert result.success and result.commit_hash, result.error
    assert targeted.calls[0] == [TARGET], targeted.calls
    assert NEW in targeted.calls[1], targeted.calls


# F3
async def test_a_refusal_blocks_the_commit_whatever_the_syntax_state(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    result = await _build(repo, [_create(NEW, "ok = 1\n"), _create(REFUSED, "x = 1\n")])
    assert result.files_written == [NEW], "premise: the admitted file was written and parses"
    assert result.success is False and not result.commit_hash
    assert result.error.startswith("Syntax errors") and "Path traversal blocked" in result.error, result.error
    assert not (repo / NEW).exists(), "the failed build deletes the file it created"


# F4
async def test_a_build_with_a_refusal_runs_no_tests_review_or_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {NEW}===\nok = 2\n===END FILE===\n")
    result = await _build(repo, [_create(NEW, "ok = 1\n"), _create(REFUSED, "x = 1\n")], run_tests=True, llm_client=model)
    assert result.files_written == [NEW], "premise: the admitted file was written"
    assert targeted.calls == [], "a build holding a refusal runs no model-written tests"
    assert model.complete.await_count == 0, "and asks for no review and no repair"
    assert result.success is False and "Path traversal blocked" in result.error, result.error
    assert not (repo / NEW).exists()


# F5
@pytest.mark.parametrize("where", ["main-create", "main-modify", "repair"])
async def test_a_syntax_error_still_there_after_the_loop_blocks_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    model: _FakeModel | None = None
    if where == "repair":
        targeted = _Targeted([False, True])
        changes = [_modify(TARGET, "x = 1", "x = 2")]
        model = _FakeModel(f"===FILE: {BAD}===\n{BROKEN}===END FILE===\n")
        broken = BAD
    else:
        targeted = _Targeted([True])
        changes = [_create(BAD, BROKEN)] if where == "main-create" else [_modify(TARGET, "x = 1", "x = (")]
        broken = BAD if where == "main-create" else TARGET
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    result = await _build(repo, changes, run_tests=True, llm_client=model)
    assert result.tests_passed is True, "premise: the last test run passed"
    assert result.success is False and not result.commit_hash
    assert result.error.startswith("Syntax errors") and str(repo / broken) in result.error, result.error


# F6
@pytest.mark.parametrize("left", ["broken", "deleted", "undecodable", "directory"])
async def test_the_syntax_state_is_read_from_the_files_the_tests_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, left: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW

    async def tests_that_change_the_file(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        if left == "broken":
            created.write_bytes(BROKEN.encode("utf-8"))
        elif left == "deleted":
            created.unlink()
        elif left == "undecodable":
            created.write_bytes(b"\xff\xfe = 1\n")
        else:  # BF-904b A3: a directory where the file was
            created.unlink()
            created.mkdir()
        return True, "1 passed", ["tests/test_fresh.py"]

    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_that_change_the_file)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    expected = {
        "broken": "line 1",
        "deleted": "is no longer a regular file",
        "undecodable": "could not be read for the syntax check (UnicodeDecodeError)",
        "directory": "is no longer a regular file",
    }[left]
    assert result.tests_passed is True, "premise: the tests passed"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and str(created) in result.error and expected in result.error, result.error
    if left != "directory":  # BF-904b A3: a directory the tests left is reported by the cleanup, not removed
        assert not created.exists(), "the failed build deletes the file it created"


def _alias(link: Path, target: Path) -> bool:
    """Make *link* an alias of *target*: a symbolic link, else on Windows a junction to a directory; False if neither."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt" or not target.is_dir():
        return False
    made = _REAL_RUN(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True, check=False,
        stdin=subprocess.DEVNULL, timeout=60,
    )
    return made.returncode == 0 and os.path.isjunction(link)


# F7
@pytest.mark.parametrize("where", ["ancestor", "leaf"])
async def test_an_alias_the_tests_leave_is_refused_and_its_target_never_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW
    outside = tmp_path / "outside" / "newpkg"
    outside.mkdir(parents=True)
    (outside / "fresh.py").write_bytes(OUTSIDE_TEXT.encode("utf-8"))
    link, target = (created.parent, outside) if where == "ancestor" else (created, outside / "fresh.py")
    if not _alias(tmp_path / "probe", target):
        pytest.skip("this host can make neither a symbolic link nor a junction for this alias")
    made: list[bool] = []

    async def tests_that_leave_an_alias(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        created.unlink()
        if where == "ancestor":
            created.parent.rmdir()
        made.append(_alias(link, target))
        return True, "1 passed", ["tests/test_fresh.py"]

    real_parse = builder_module.ast.parse
    parsed: list[Any] = []

    def parse_and_record(source: Any, *args: Any, **kwargs: Any) -> Any:
        parsed.append(source)
        return real_parse(source, *args, **kwargs)

    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_that_leave_an_alias)
    monkeypatch.setattr(builder_module.ast, "parse", parse_and_record)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    assert made == [True] and result.tests_passed is True, "premise: the tests passed and left the alias"
    assert OUTSIDE_TEXT not in parsed, "the text outside the work tree is never parsed"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and f"{created}: resolves outside the work tree; refused" in result.error, result.error
    # Not asserted: that the outside file outlives the build. The failed build's cleanup deletes the created path
    # through an ancestor alias (_restore_pre_build_files); that is F-124 on #1523, not the syntax read.


# F8
@pytest.mark.parametrize("fault", ["stat-fails", "swapped-before-open"])
async def test_a_file_that_cannot_be_examined_after_the_tests_is_one_syntax_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW
    names = {os.path.normcase(os.path.abspath(name)) for name in (created, os.path.join(os.path.realpath(repo), NEW))}
    armed: list[bool] = []
    faults: list[str] = []

    def failing(real_call: Any) -> Any:
        def call(target: Any, *args: Any, **kwargs: Any) -> Any:
            if armed and not isinstance(target, int) and os.path.normcase(os.path.abspath(os.fspath(target))) in names:
                faults.append(os.fspath(target))
                raise _Denied(13, "injected stat failure", os.fspath(target))
            return real_call(target, *args, **kwargs)

        return call

    def swapped_open(name: str, flags: int) -> int:
        return os.open(repo / OTHER, os.O_RDONLY | getattr(os, "O_BINARY", 0))

    async def tests_then_arm(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        armed.append(True)
        return True, "1 passed", ["tests/test_fresh.py"]

    real_syntax_errors = builder_module._syntax_errors

    def syntax_then_disarm(*args: Any) -> list[str]:
        try:
            return real_syntax_errors(*args)
        finally:
            armed.clear()  # the cleanup's own examination of the file runs unfaulted

    if fault == "stat-fails":
        monkeypatch.setattr(os, "stat", failing(os.stat))
        monkeypatch.setattr(os, "lstat", failing(os.lstat))
    else:
        # raising=False: before A3 there is no opener to replace, and the build must then fail the assertions below.
        monkeypatch.setattr(builder_module, "_syntax_read_opener", swapped_open, raising=False)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_then_arm)
    monkeypatch.setattr(builder_module, "_syntax_errors", syntax_then_disarm)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    expected = {
        "stat-fails": "could not be read for the syntax check (PermissionError)",
        "swapped-before-open": "changed while it was read",
    }[fault]
    assert result.tests_passed is True, "premise: the tests passed"
    assert fault != "stat-fails" or faults, "premise: the injected failure fired after the tests"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and f"{created}: {expected}; refused" in result.error, result.error
    assert not created.exists(), "the failed build deletes the file it created"
```

### 7.10 `src/probos/build_queue.py` (M3)

SEARCH:
```python
    "reviewing": {"merged", "failed"},
}
```
REPLACE:
```python
    "reviewing": {"merged", "failed"},
}

# BF-904b (#1585): the statuses in which a build holds its file footprint, from dispatch until it is merged or
# failed. A build in review counts, or a second build on the same files would be generated against the same base.
_FOOTPRINT_HOLDING_STATUSES = ("dispatched", "building", "reviewing")
```

SEARCH:
```python
    def has_footprint_conflict(self, footprint: list[str]) -> bool:
        """Check if any active build has overlapping file footprint."""
        fp_set = set(footprint)
        for b in self._builds:
            if b.status in ("dispatched", "building"):
```
REPLACE:
```python
    def has_footprint_conflict(self, footprint: list[str]) -> bool:
        """Check if any build that holds its files has an overlapping file footprint (BF-904b: review included)."""
        fp_set = set(footprint)
        for b in self._builds:
            if b.status in _FOOTPRINT_HOLDING_STATUSES:
```

### 7.11 `src/probos/cognitive/builder.py` (M3)

SEARCH:
```python
        # Step 2: If files are large, use localization to select relevant sections
        if total_size > self._LOCALIZE_THRESHOLD:
```
REPLACE:
```python
        # BF-904b (#1585): the whole files, kept for the visiting builder. Only the native prompt context below
        # (and the Transporter's size estimate) uses the localized excerpts.
        full_files = dict(all_files)

        # Step 2: If files are large, use localization to select relevant sections
        if total_size > self._LOCALIZE_THRESHOLD:
```

SEARCH:
```python
                # Copy existing target files into temp dir (preserving structure).
                # BF-896: the helper the dispatcher uses; a key naming a path outside
                # the temp dir (an absolute target) is skipped, not written there.
                seed_session_directory(tmp_dir, all_files)
```
REPLACE:
```python
                # Copy existing target files into temp dir (preserving structure).
                # BF-896: the helper the dispatcher uses; a key naming a path outside
                # the temp dir (an absolute target) is skipped, not written there.
                # BF-904b (#1585): whole files, and the adapter is given what was seeded (as the
                # dispatcher does), because its scan takes each change's "base" from that mapping.
                seeded = seed_session_directory(tmp_dir, full_files)
```

SEARCH:
```python
                await adapter.start()
                try:
                    copilot_result = await adapter.execute(spec, all_files)
                finally:
```
REPLACE:
```python
                await adapter.start()
                try:
                    copilot_result = await adapter.execute(spec, seeded)
                finally:
```

SEARCH:
```python
        # Transporter Pattern result — blocks already parsed
        if decision.get("action") == "transporter_complete":
            file_changes = decision.get("file_changes", [])
```
REPLACE:
```python
        # Transporter Pattern result — blocks already parsed
        if decision.get("action") == "transporter_complete":
            # BF-904b (#1585): project-relative paths, as the single-pass route below gives them; a
            # CodebaseIndex-relative path would otherwise be refused at the write boundary.
            file_changes = _normalize_change_paths(decision.get("file_changes", []))
```

### 7.12 `tests/test_bf896_executor_identity_and_blocks.py` (M3: the test's premise was the excerpt reaching the adapter)

SEARCH:
```python
    target = tmp_path / "big_target.py"
    target.write_bytes(original.encode("utf-8"))
```
REPLACE:
```python
    target = tmp_path / "big_target.py"
    target.write_bytes(original.encode("utf-8"))
    # BF-904b (#1585): an old modification time, so a rewrite with the same bytes is visible too (below).
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
```

SEARCH:
```python
    # premise: the absolute key reached the adapter carrying an excerpt, not the file
    key = str(target)
    assert os.path.isabs(key) and key in adapter.files
    assert adapter.files[key] != original and len(adapter.files[key]) < len(original), "premise: the target was localized"

    assert target.read_bytes() == original.encode("utf-8"), "the original file outside the temp dir was rewritten"
```
REPLACE:
```python
    # BF-904b (#1585): this premise used to be that the absolute key reached the adapter carrying an excerpt. The
    # adapter now gets the mapping the seed returns (whole files, session-relative keys), so the absolute key is
    # dropped before the adapter as well as from the disk, and a rewrite would write the same bytes: the test
    # also pins the file's modification time, set to an old value above.
    key = str(target)
    assert os.path.isabs(key) and key not in adapter.files, "the absolute key is not handed to the adapter"

    assert target.read_bytes() == original.encode("utf-8"), "the original file outside the temp dir was rewritten"
    assert target.stat().st_mtime_ns == 1_000_000_000, "the original file outside the temp dir was written again"
```

### 7.13 New file: `tests/test_bf904b_dispatch_and_visiting.py` (M3)

```python
"""BF-904b (#1585), milestone M3: a build in review holds its files (item 6), and the visiting builder works from
whole files with project-relative change paths (item 7).

Before M3 ``BuildQueue.has_footprint_conflict`` counted only ``dispatched`` and ``building``, so a second build on
the same files was dispatched while the first waited in review. ``BuilderAgent.perceive`` seeded the visiting
session with the localization excerpts and handed them to the adapter, whose scan takes each whole-file change's
``base`` from that mapping, so ``execute_approved_build`` refused every such change to a localized target; and
``act`` returned ``transporter_complete`` changes without ``_normalize_change_paths``.

Rules: the real ``BuildQueue`` and ``BuildDispatcher``; the real ``BuilderAgent`` (``perceive``, ``decide``,
``act``) with ``_PROJECT_ROOT`` and ``_SOURCE_ROOT`` pointed at a source tree under ``tmp_path``; the real
``seed_session_directory`` and ``execute_approved_build`` on real git. The adapter is a stand-in (no SDK here) whose
change is built the way its disk scan builds one. No sleeps; every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.build_dispatcher import BuildDispatcher
from probos.build_queue import BuildQueue
from probos.cognitive import builder as builder_module
from probos.cognitive import copilot_adapter as adapter_module
from probos.cognitive.builder import BuilderAgent, BuildSpec, execute_approved_build
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeManager

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

BIG = "src/probos/big.py"
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf904b@example.invalid"),
        ("config", "user.name", "BF904b Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout.replace("\r\n", "\n")


def _spec(title: str, files: list[str] | tuple[str, ...] = ()) -> BuildSpec:
    return BuildSpec(title=title, description="d", target_files=list(files))


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


def _big_text() -> str:
    return "".join(f"value_{i:04d} = {i}  # padding that makes this file large enough to be localized\n" for i in range(800))


class _Generated:
    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        self.success = True
        self.file_blocks = blocks
        self.raw_output = "visiting"
        self.error = None


class _VisitingProbe:
    """Stands in for ``CopilotBuilderAdapter``. It records the mapping ``execute`` receives and what the session
    directory holds then, and answers with one whole-file change built as the adapter's disk scan builds one
    (``content`` the new text, ``base`` the text it was given for that path)."""

    last: Any = None

    def __init__(self, *, cwd: str = "", **_kw: Any) -> None:
        self.cwd = cwd
        self.files: dict[str, str] | None = None
        self.seeded: dict[str, bytes] | None = None
        type(self).last = self

    async def start(self) -> None:
        return None

    async def execute(self, _spec: Any, files: dict[str, str]) -> _Generated:
        self.files = dict(files)
        root = Path(self.cwd)
        self.seeded = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        given = files.get(BIG, "")
        return _Generated([{"path": BIG, "mode": "modify", "content": given + "extra = 1\n", "base": given}])

    async def stop(self) -> None:
        return None


def _source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source"
    (source / "src" / "probos").mkdir(parents=True)
    (source / BIG).write_bytes(_big_text().encode("utf-8"))
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", source)
    monkeypatch.setattr(builder_module, "_SOURCE_ROOT", source / "src" / "probos")
    _VisitingProbe.last = None
    monkeypatch.setattr(adapter_module, "CopilotBuilderAdapter", lambda **kw: _VisitingProbe(**kw))
    return source


def _agent() -> Any:
    return BuilderAgent(agent_id="builder-bf904b", llm_client=MagicMock(), runtime=MagicMock(spec=ProbOSRuntime))


async def _perceive_visiting(agent: Any) -> dict:
    return await _bounded(agent.perceive({
        "intent": "build_code",
        "params": {"title": "t", "description": "d", "target_files": [BIG], "force_visiting": True},
    }))


# D1
async def test_a_build_in_review_holds_its_files() -> None:
    queue = BuildQueue()
    first = queue.enqueue(_spec("first", ["src/probos/a.py"]))
    for status in ("dispatched", "building", "reviewing"):
        assert queue.update_status(first.id, status), f"premise: {status}"
    second = queue.enqueue(_spec("second", ["src/probos/a.py", "src/probos/b.py"]), priority=1)
    third = queue.enqueue(_spec("third", ["src/probos/c.py"]), priority=5)
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.remove = AsyncMock()
    dispatcher = BuildDispatcher(queue=queue, worktree_mgr=worktrees)
    assert queue.has_footprint_conflict(second.file_footprint) is True
    picked = dispatcher._find_dispatchable()
    assert picked is not None and picked.id == third.id, "the overlapping build waits; a disjoint one goes"
    assert await dispatcher.reject_build(first.id) is True
    assert queue.has_footprint_conflict(second.file_footprint) is False
    picked = dispatcher._find_dispatchable()
    assert picked is not None and picked.id == second.id, "rejecting the reviewed build releases its files"


# D2
@pytest.mark.parametrize(
    ("statuses", "holds"),
    [
        ((), False),
        (("dispatched",), True),
        (("dispatched", "building"), True),
        (("dispatched", "building", "reviewing"), True),
        (("dispatched", "building", "reviewing", "merged"), False),
        (("dispatched", "building", "failed"), False),
    ],
    ids=["queued", "dispatched", "building", "reviewing", "merged", "failed"],
)
def test_which_statuses_hold_a_builds_files(statuses: tuple[str, ...], holds: bool) -> None:
    queue = BuildQueue()
    build = queue.enqueue(_spec("held", ["src/probos/a.py"]))
    for status in statuses:
        assert queue.update_status(build.id, status), f"premise: {status}"
    assert queue.has_footprint_conflict(["src/probos/a.py"]) is holds


# V1
async def test_the_visiting_builder_is_seeded_with_whole_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _source_tree(tmp_path, monkeypatch)
    original = _big_text()
    assert len(original) > BuilderAgent._LOCALIZE_THRESHOLD, "premise: perceive localizes this target"
    obs = await _perceive_visiting(_agent())
    probe = _VisitingProbe.last
    assert probe is not None and probe.files is not None and probe.seeded is not None, "premise: the visiting route ran"
    assert "omitted" in obs["target_context"], "control: the native prompt context is still the excerpt"
    assert probe.files[BIG] == original, "the visiting builder is handed the whole file"
    assert probe.seeded[BIG].decode("utf-8").replace("\r\n", "\n") == original, "and the session directory holds it"


# V2
@needs_git
async def test_a_whole_file_change_from_the_visiting_builder_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _source_tree(tmp_path, monkeypatch)
    original = _big_text()
    repo = _init_repo(tmp_path / "repo", {BIG: original})
    agent = _agent()
    obs = await _perceive_visiting(agent)
    decision = await _bounded(agent.decide(obs))
    assert decision.get("action") == "transporter_complete", "premise: the visiting route answered"
    acted = await _bounded(agent.act(decision))
    changes = acted["result"]["file_changes"]
    assert [change["path"] for change in changes] == [BIG], changes
    result = await _bounded(execute_approved_build(changes, _spec("bf904b visiting", [BIG]), str(repo), run_tests=False))
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, BIG) == original + "extra = 1\n"


# V3
@needs_git
@pytest.mark.parametrize("source", ["transporter", "visiting"])
async def test_transporter_changes_get_project_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    tree = tmp_path / "source"
    (tree / "src" / "probos" / "pkg").mkdir(parents=True)
    (tree / "src" / "probos" / "pkg" / "mod.py").write_bytes(b"v = 1\n")
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", tree)
    monkeypatch.setattr(builder_module, "_SOURCE_ROOT", tree / "src" / "probos")
    decision: dict[str, Any] = {
        "action": "transporter_complete",
        "file_changes": [_modify("pkg/mod.py", "v = 1", "v = 2")],
        "llm_output": "bf904b",
    }
    if source == "visiting":
        decision["builder_source"] = "visiting"
    acted = await _bounded(_agent().act(decision))
    changes = acted["result"]["file_changes"]
    assert [change["path"] for change in changes] == ["src/probos/pkg/mod.py"], changes
    repo = _init_repo(tmp_path / "repo", {"src/probos/pkg/mod.py": "v = 1\n"})
    result = await _bounded(execute_approved_build(changes, _spec("bf904b paths"), str(repo), run_tests=False))
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, "src/probos/pkg/mod.py") == "v = 2\n"
```

## 8. Tracking (tracker pairs; in M3's commit)

**`PROGRESS.md`** (anchored on the title, the blank line and the bold lead of BF-901 S3's head entry, unchanged on the merged main):

SEARCH:
```markdown
# ProbOS Progress

**BF-901 S3 (2026-10-21), closes #1575 -- the doctor shows what the journal says was spent, measured and estimated apart.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-904b (2026-10-22), closes #1585 -- the sealed-core observation can fire, a syntax error a repair fixed no longer blocks the commit, a build in review holds its files, and the visiting builder works from whole files.** Items 2, 4, 6 and 7 of #1585 (BF-904a did 1, 3 and 5). Item 2: the /api/build resolve route and the build dispatcher now pass `enforce_sealed_core` to `execute_approved_build` (the route reads its runtime's config; the dispatcher is given `config.extensions.enforce_sealed_core` at boot). The policy is this ProbOS's own `config/sealed_modules.yaml`, read only when the flag is on, and the change path is matched repository-relative with `/` separators and case folded. It is still a warning per write, never a refusal (AD-481l). Item 4: refusals stay in `validation_errors` and are permanent; syntax is read again at the commit decision on the files as the build and its tests left them, so an error a repair fixed no longer blocks, and the targeted tests are recomputed at each attempt. A build that already holds a refusal runs no review, tests or repair (#1523 F-153 item 18). Item 6: `reviewing` holds a build's files in `BuildQueue.has_footprint_conflict`; `_git_create_branch`'s force-delete was already gone (BF-904a D31). Item 7: the visiting builder is seeded with, and handed, whole files (the excerpts stay the native prompt's), and `transporter_complete` changes go through `_normalize_change_paths`. New: `tests/test_bf904b_sealed_core_observation.py`, `tests/test_bf904b_fix_loop_state.py` and `tests/test_bf904b_dispatch_and_visiting.py` (real git, the real `is_sealed_path` and policy, the real `BuildQueue`, `BuildDispatcher`, `BuildPipeline` and `BuilderAgent`, and a real boot). Updated where they pinned the old behaviour: `test_ad481_extensions.py`, `test_bf898_fix_loop_grader_protection.py` and `test_bf896_executor_identity_and_blocks.py`. The contract is `prompts/bf-904b-native-build-residuals.md`.

**BF-901 S3 (2026-10-21), closes #1575 -- the doctor shows what the journal says was spent, measured and estimated apart.**
```

**`DECISIONS.md`** (after BF-901 S3's entry, anchored on its *Reversal* bullet, the blank line and the heading that follows; the docs-only commit adds BF-904b's *Validation of record* bullet above BF-904b's own *Reversal* line):

SEARCH:
```markdown
- *Reversal.* Revert the BF-901 S3 commit. Nothing persisted changes; the doctor loses the check and the `detail` field, which no other check sets.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-901 S3 commit. Nothing persisted changes; the doctor loses the check and the `detail` field, which no other check sets.

### BF-904b -- The sealed-core observation can fire, refusals and syntax state are kept apart, a build in review holds its files, and the visiting builder works from whole files (2026-10-22, closes #1585)

- *Scope.* Items 2, 4, 6 and 7 of #1585 (BF-904a: 1, 3 and 5), in three milestone commits, one gate and one PR. `cognitive/builder.py` (`sealed_core_enforced`, `_sealed_globs`, `_check_sealed_path`, `_syntax_errors`, `execute_approved_build`, `BuilderAgent.perceive` and `act`), `routers/build.py`, `build_dispatcher.py`, `startup/structural_services.py`, `build_queue.py` and tests. Contract: `prompts/bf-904b-native-build-residuals.md`.
- *D1 (premise).* Item 6's branch clause was met by BF-904a D31: `_git_create_branch` refuses an existing branch, and the one `branch -D` left deletes only the branch the same call created, after nothing was committed and the return succeeded. Recorded, not rebuilt.
- *D3-D5 (item 2).* A flag, not the runtime. Passing the runtime would switch on the pre-flight runner and Hebbian recording for the /api/build routes, and the dispatcher would hold the whole runtime. The route reads its runtime's config (True only for the boolean True; a runtime without config reads False, as the old check's AttributeError branch did); the dispatcher is given the flag at construction; `BuildPipeline` keeps its runtime path. The policy is this ProbOS's own file, never the work tree's (a build can write `config/`) or one relative to the working directory. The admitted change path is matched with `/` separators, `.` and doubled separators removed, and case folded on both sides; a link or junction alias is F-124's. "Observed" is one warning per write at each of the four write sites; with the flag off nothing is read, matched or logged; no build outcome changes (AD-481l is the hard block).
- *D6-D7 (item 4).* `validation_errors` holds refusals, which are permanent. Syntax is a set of the paths a write validated, read at 5.5 on the files as they are then; the error keeps its `Syntax errors:` lead, refusals first. The targeted tests' file list is read at each attempt. A build holding a refusal before the review runs no review, tests or repair (#1523 F-153 item 18, and with it the BF-904b part of item 20).
- *D8 (not taken).* `classify_build_failure`'s substring matching (F-153 item 4) stays in the register: item 4 adds no string it matches, every resolution re-runs the guarded executor, and after an incomplete cleanup only abort is taken (BF-904a D30). Git's stdout captured whole (F-153 item 1) is not touched by these items; AD-1335's or its own slice.
- *D9 (item 6).* `dispatched`, `building` and `reviewing` hold a build's footprint; `queued`, `merged` and `failed` do not; the queue has no other status. `active_count` is unchanged. No race opens: a build is found and marked dispatched with no await between.
- *D10 (item 7).* The visiting builder is seeded with and handed whole files, and the adapter gets the mapping the seed returns, as the dispatcher does, because its scan takes `base` from it. The native prompt context and the Transporter's size estimate keep the excerpts. Every `transporter_complete` change is normalised; a project-relative path, the native harness's included, is unchanged by it.
- *Disclosed effects.* With `enforce_sealed_core` on, writes to sealed paths now log (default off). A build with a refusal runs no review, tests or repair. A build in review blocks overlapping queued builds until it is rejected (delivery refuses under BF-897). The visiting prompt carries whole files. Syntax errors are listed once per file, after the refusals. A Python file the tests deleted, made a non-regular file or left undecodable fails the build before `git add`.
- *Reversal.* Revert the three BF-904b commits. Nothing persisted changes; the observation stops firing, refusals and syntax share one list again, a build in review stops holding its files and the visiting builder is seeded with excerpts again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M3's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the code commits:** a *Validation of record* bullet in BF-904b's entry, before its *Reversal* line (the mutation campaign of record: base tree and the sha256 of each file in §10 and of the three new test files, each row's first failing test). Add a closing section to this contract with the same, then run the ledger regeneration again.

**`docs/development/roadmap.md`:** no row (BF-904a added none; `grep -c BF-904 docs/development/roadmap.md` is 0).

## 9. What this does NOT change

- AD-481l (no refusal for a sealed path); `config/sealed_modules.yaml`; `extensions/sealed_core.py`.
- `builder_write_refusal`, `fix_loop_write_refusal`, `fix_loop_path`, the write-boundary policy (F-124 owns aliases).
- Test sandboxing (AD-1334, AD-1335); BF-904a's git hardening, restore and unapplied-block refusals.
- The native harness route (F-120), the worktree start point (F-121), `config/system.yaml`, `config_models/agentic.py`.
- `classify_build_failure`, the resolution options, `/api/build/resolve`'s rules (BF-904a D30), `_run_git`.
- `BuildPipeline`, `CopilotBuilderAdapter`, `seed_session_directory`, `_localize_context`, `_should_use_transporter`, `transporter_build`.
- `BuildQueue.active_count`, its transitions, `BuildDispatcher` concurrency, `WorktreeManager`.

## 10. Mutation rows (54 rows; whole stripped lines; each occurs once in its file after §7)

Tier HIGH: every changed production file has rows. Run each row against the three new test files on the contract-applied tree, after an unmutated baseline run of those files that passes. A18's killer is the updated pin in `tests/test_bf896_executor_identity_and_blocks.py` (7.5b), not a new file: run that test alone against the mutant, after an unmutated run of it that passes. Restore each file before the next row. "First failing" is in file order (S, then F, then D/V); where another test fails first, run the named one alone against the mutant.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| A1 | `src/probos/cognitive/builder.py` | `return runtime.config.extensions.enforce_sealed_core is True` | `return False` | S5 `[flag-on]` (also S8) |
| A2 | `src/probos/cognitive/builder.py` | `observe_sealed = enforce_sealed_core if enforce_sealed_core is not None else sealed_core_enforced(runtime)` | `observe_sealed = sealed_core_enforced(runtime)` | S1 `[modify]` |
| A3 | `src/probos/cognitive/builder.py` | `sealed_globs = _sealed_globs() if observe_sealed is True else ()` | `sealed_globs = ()` | S1 `[modify]` |
| A4 | `src/probos/cognitive/builder.py` | `sealed_globs = _sealed_globs() if observe_sealed is True else ()` | `sealed_globs = _sealed_globs()` | S3 `[off]` (the policy is read with the flag off) |
| A5 | `src/probos/cognitive/builder.py` | `return load_sealed_globs(str(_SEALED_POLICY))` | `return load_sealed_globs()` | S4 (S1 and S2 first when pytest's working directory is not the repository root) |
| A6 | `src/probos/cognitive/builder.py` | `if not sealed_globs:` | `if False:` | S3 `[off]` (`is_sealed_path` is called) |
| A7 | `src/probos/cognitive/builder.py` | `rel = os.path.normpath(change_path.replace("\\", "/")).replace("\\", "/").casefold()` | `rel = change_path` | S2 `[dot-and-double-slash]` on every host (`[mixed-case]` first on POSIX) |
| A8 | `src/probos/cognitive/builder.py` | `if is_sealed_path(rel, tuple(glob.casefold() for glob in sealed_globs)):` | `if is_sealed_path(rel, sealed_globs):` | S2b `[directory-itself]` on every host (`[file]` first on POSIX) |
| A9 | `src/probos/cognitive/builder.py` | `_check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's modify` | `pass` | S1 `[modify]` |
| A10 | `src/probos/cognitive/builder.py` | `_check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's create` | `pass` | S1 `[create]` |
| A11 | `src/probos/cognitive/builder.py` | `_check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's modify` | `pass` | S1 `[repair-modify]` |
| A12 | `src/probos/cognitive/builder.py` | `_check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's create` | `pass` | S1 `[repair-create]` |
| A13 | `src/probos/routers/build.py` | `enforce_sealed_core=sealed_core_enforced(rt),  # BF-904b (#1585): the runtime's flag; no runtime is passed` | `enforce_sealed_core=None,` | S5 `[flag-on]` |
| A14 | `src/probos/build_dispatcher.py` | `enforce_sealed_core=self._enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation` | `enforce_sealed_core=False,` | S6 `[on]` |
| A15 | `src/probos/build_dispatcher.py` | `self._enforce_sealed_core = enforce_sealed_core` | `self._enforce_sealed_core = False` | S6 `[on]` |
| A16 | `src/probos/build_dispatcher.py` | `return self._enforce_sealed_core` | `return False` | S6 `[on]` (the property assertion; also S7) |
| A17 | `src/probos/startup/structural_services.py` | `enforce_sealed_core=config.extensions.enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation, off by default` | `enforce_sealed_core=False,` | S7 |
| A18 | `src/probos/cognitive/builder.py` | `specialty: str = "general",` | `*, specialty: str = "general",` | 7.5b `test_expected_git_dir_keeps_its_position_and_only_optional_parameters_follow_it` in `tests/test_bf896_executor_identity_and_blocks.py` (the kind assertion: a positional call would no longer reach `specialty` or `expected_git_dir`); run it alone |
| A19 | `src/probos/cognitive/builder.py` | `except Exception as exc:  # BF-904b A4: third-party parsing of an external file; its failure set is open` | `except (OSError, ValueError, RecursionError) as exc:` | S9 `[overflow]` (the `BUILD_SUCCESS` assertion; also `[unknown-bool]`, `[empty-int]`, `[bad-timestamp]`, `[unlisted-class]`: the round-2 guard) (Amendment A2; rewritten by Amendment A4) |
| A20 | `src/probos/cognitive/builder.py` | `except Exception as exc:  # BF-904b A4: third-party parsing of an external file; its failure set is open` | `except (OSError, ValueError, RecursionError, OverflowError, KeyError, IndexError, AttributeError) as exc:` | S9 `[unlisted-class]` (the `BUILD_SUCCESS` assertion: a closed list misses a class no list names) (Amendment A2; rewritten by Amendment A4) |
| A21 | `src/probos/cognitive/builder.py` | `_SEALED_POLICY, type(exc).__name__,` | `_SEALED_POLICY, "",` | S9 `[not-utf-8]` (the exception-class assertion) (Amendment A2) |
| A22 | `src/probos/cognitive/builder.py` | `_SEALED_POLICY, type(exc).__name__,` | `"", type(exc).__name__,` | S9 `[not-utf-8]` (the path assertion) (Amendment A2) |
| A23 | `src/probos/cognitive/builder.py` | `return ()  # BF-904b A2: no globs, so nothing is observed and the build goes on` | `raise` | S9 `[not-utf-8]` (the `BUILD_SUCCESS` assertion) (Amendment A2) |
| A24 | `src/probos/cognitive/builder.py` | `except MemoryError:` | `except (MemoryError, RecursionError):` | S9 `[deep-nesting]` (the `BUILD_SUCCESS` assertion: the re-raise lets the recursion out) (Amendment A4) |
| A25 | `src/probos/cognitive/builder.py` | `raise  # BF-904b A4: the process is out of memory, not the policy unreadable; the build fails as before` | `return ()` | S10 (the `pytest.raises` assertion) (Amendment A4) |
| A26 | `src/probos/cognitive/builder.py` | `except MemoryError:` | `except ZeroDivisionError:` | S10 (the `MemoryError` reaches the `except Exception` and is degraded) (Amendment A4) |
| B1 | `src/probos/cognitive/builder.py` | `syntax_checked[path] = None  # BF-904b: a main-loop modify, read again at 5.5` | `pass` | F5 `[main-modify]` |
| B2 | `src/probos/cognitive/builder.py` | `syntax_checked[path] = None  # BF-904b: a main-loop create, read again at 5.5` | `pass` | F5 `[main-create]` |
| B3 | `src/probos/cognitive/builder.py` | `syntax_checked[path] = None  # BF-904b: a repair's file, read again at 5.5` | `pass` | F5 `[repair]` |
| B4 | `src/probos/cognitive/builder.py` | `all_changed_files = written + modified_files` | `all_changed_files = all_changed_files if attempt else written + modified_files` | F2 |
| B5 | `src/probos/cognitive/builder.py` | `syntax_errors = _syntax_errors(Path(work_dir), list(syntax_checked))` | `syntax_errors = []` | F5 `[main-create]` (line updated by Amendment A3) |
| B6 | `src/probos/cognitive/builder.py` | `elif validation_errors or syntax_errors:` | `elif syntax_errors:` | F3 |
| B7 | `src/probos/cognitive/builder.py` | `elif validation_errors or syntax_errors:` | `elif validation_errors:` | F5 `[main-create]` |
| B8 | `src/probos/cognitive/builder.py` | `result.error = "Syntax errors:\n" + "\n".join(validation_errors + syntax_errors)` | `result.error = "Syntax errors:\n" + "\n".join(validation_errors)` | F5 `[main-create]` (the file is not named) |
| B9 | `src/probos/cognitive/builder.py` | `if llm_client and (written or modified_files) and not validation_errors:` | `if llm_client and (written or modified_files):` | F4 (the model is called) |
| B10 | `src/probos/cognitive/builder.py` | `if run_tests and (written or modified_files) and not validation_errors:` | `if run_tests and (written or modified_files):` | F4 (the targeted tests run) |
| B11 | `src/probos/cognitive/builder.py` | `if not stat.S_ISREG(info.st_mode):` | `if False:` | F6 `[directory]` (the open of a directory is a "could not be read" line, not "is no longer a regular file") (Amendment A3) |
| B12 | `src/probos/cognitive/builder.py` | `except (OSError, ValueError) as exc:` | `except OSError as exc:` | F6 `[undecodable]` |
| B13 | `src/probos/cognitive/builder.py` | `if message is not None:` | `if False:` | F5 `[main-create]` |
| B14 | `src/probos/cognitive/builder.py` | `real = os.path.realpath(path)` | `real = os.path.abspath(path)` | F7 `[ancestor]` (the outside-text assertion: the `lstat` and the open follow the ancestor alias) (Amendment A3) |
| B15 | `src/probos/cognitive/builder.py` | `if not Path(os.path.normcase(real)).is_relative_to(os.path.normcase(os.path.realpath(root))):` | `if False:` | F7 `[ancestor]` (the outside-text assertion) (Amendment A3) |
| B16 | `src/probos/cognitive/builder.py` | `raise _SyntaxReadRefused("resolves outside the work tree")` | `pass` | F7 `[ancestor]` (the outside-text assertion) (Amendment A3) |
| B17 | `src/probos/cognitive/builder.py` | `raise _SyntaxReadRefused("is no longer a regular file") from None` | `pass` | F6 `[deleted]` (an unbound `info` raises, which is not a line) (Amendment A3) |
| B18 | `src/probos/cognitive/builder.py` | `raise _SyntaxReadRefused("changed while it was read")` | `pass` | F8 `[swapped-before-open]` (Amendment A3) |
| B19 | `src/probos/cognitive/builder.py` | `if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, info):` | `if not stat.S_ISREG(opened.st_mode):` | F8 `[swapped-before-open]` (Amendment A3) |
| B20 | `src/probos/cognitive/builder.py` | `message = f"{path}: {exc}; refused"` | `message = None` | F7 `[ancestor]` (the line assertion) (Amendment A3) |
| B21 | `src/probos/cognitive/builder.py` | `message = _python_syntax_error(path, _work_tree_text(root, path))` | `message = None` | F5 `[main-create]` (Amendment A3) |
| B22 | `src/probos/cognitive/builder.py` | `with open(real, encoding="utf-8", opener=_syntax_read_opener) as stream:` | `with open(real, encoding="utf-8") as stream:` | F8 `[swapped-before-open]` (the open no longer goes through the opener) (Amendment A3) |
| C1 | `src/probos/build_queue.py` | `_FOOTPRINT_HOLDING_STATUSES = ("dispatched", "building", "reviewing")` | `_FOOTPRINT_HOLDING_STATUSES = ("dispatched", "building")` | D1 |
| C2 | `src/probos/build_queue.py` | `if b.status in _FOOTPRINT_HOLDING_STATUSES:` | `if b.status in ("dispatched", "building"):` | D1 |
| C3 | `src/probos/cognitive/builder.py` | `full_files = dict(all_files)` | `full_files = {}` | V1 |
| C4 | `src/probos/cognitive/builder.py` | `seeded = seed_session_directory(tmp_dir, full_files)` | `seeded = seed_session_directory(tmp_dir, all_files)` | V1 |
| C5 | `src/probos/cognitive/builder.py` | `copilot_result = await adapter.execute(spec, seeded)` | `copilot_result = await adapter.execute(spec, all_files)` | V1 |
| C6 | `src/probos/cognitive/builder.py` | `file_changes = _normalize_change_paths(decision.get("file_changes", []))` | `file_changes = decision.get("file_changes", [])` | V3 `[transporter]` |

Lines without a row: the docstrings and comments; `errors: list[str] = []` and `return errors` (any change breaks every F test); the dispatcher's signature line (S6 covers the keyword); the executor's `expected_git_dir` and `enforce_sealed_core` parameter lines (each contains a `|`, which a table cell cannot hold as one string; A18 mutates the `specialty` line instead, removing the flag's default is a syntax error, and by §6's premises S3 `[unset-without-runtime]` and S8 cover a changed default). In `_sealed_globs` (Amendment A2): `try:` (removing or rewriting it is a syntax error); `logger.warning(` and its closing `)` (not unique in the file; A21 and A22 mutate the arguments); the message line (its wording is not a behaviour; S9 selects the record by `sealed policy`, so a change there fails S9's count).

Amendment A3, lines without a row: `if path.suffix != ".py":` (it occurs twice, in `_validate_python` too; every F test writes only `.py` files); `return os.open(name, _HOOK_OPEN_FLAGS)` (the flags matter only in a race between the `lstat` and the open, which no deterministic test stages; B19 and B22 cover the check behind them); `info = os.lstat(real)`, `opened = os.fstat(stream.fileno())` and `return stream.read()` (any change breaks every F test that reads a file); the `_python_syntax_error` body (F5 and F6 `[broken]` kill a change to the parse; its `return f"{path}: line ...` line occurs twice); the `class _SyntaxReadRefused` line.

## 11. Verified Against Codebase (2026-10-21, tree `39b6ec2b73372aa40efc8a883fa494cd3a286061`, HEAD `90a9e040`)

Uniqueness: each SEARCH's distinctive line was grepped without a `$` anchor (the working copies are CRLF; an anchored pattern returns no lines) and counted once, or read in its whole file.

```
src/probos/cognitive/builder.py
  15: import os                                   48: _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
  51: _SOURCE_ROOT = ...                          79: def _normalize_change_paths(file_changes)
  202: def classify_build_failure(...)            231: elif "SyntaxError" in combined:
  1191: def _should_use_transporter               1222: def _should_use_visiting_builder (1238: if force_visiting: return True)
  1665-1679: _git_create_branch refuses an existing branch (A4 D31, A5 D36)
  1747-1781: _restore_pre_build_files (1766: a missing created file is skipped)
  2156: _LOCALIZE_THRESHOLD: int = 20_000       2209-2309: _localize_context returns a new dict
  2312-2327: _fallback_truncate (> 15_000 chars: head 200, tail 200, "lines omitted")
  2329-2593: perceive; 2346 all_files; 2369 "# Step 2"; 2379 all_files = localized; 2382-2397 native context
  2432: seed_session_directory(tmp_dir, all_files)      2443: copilot_result = await adapter.execute(spec, all_files)
  2516: target_size = sum(len(all_files.get(f, "")) ...)  2526/2568: work_dir=str(_PROJECT_ROOT)
  2651-2667: transporter_complete branch, no normalisation; 2694: _normalize_change_paths(file_changes)
  2772-2780: _validate_python                  2783-2788: _fix_loop_changed
  2923-2936: _classify_test_run ("1 failed" -> failed)
  3085-3112: _check_sealed_path(target_path, runtime); 3098 runtime None returns; 3106 is_sealed_path(target_path)
  3121-3133: execute_approved_build signature; 3130 runtime; 3131 specialty; 3132 expected_git_dir
  3144-3147: expected_git_dir docstring        3156: tests_ran = False      3161: operator_checkout_refusal(work_dir, _PROJECT_ROOT)
  3211-3222: pre-flight via runtime            3237: build_branch = result.branch_name
  3241: validation_errors: list[str] = []      3252-3262: refusals + BF-904a pre-pass
  3264: path = Path(work_dir) / change["path"]  3287-3296, 3310-3315: base checks
  3335-3336: if modified != original / _check_sealed_path(path, runtime)
  3350-3355: validate after modify             3357-3358: mkdir + _check_sealed_path (main create)
  3374-3377: validate after create             3393-3394: 4c review condition
  3418-3419: 5. tests condition                3427: all_changed_files = written + modified_files
  3430: for attempt in range(1 + max_fix_attempts)   3432-3434: _run_targeted_tests(work_dir, all_changed_files, timeout=...)
  3491-3513: repair refusals into validation_errors  3518: fix-loop path
  3542-3543: if mod != original / _check_sealed_path   3548-3549: mkdir / _check_sealed_path (repair create)
  3560-3563: err = _validate_python(path) ... finally:
  3613-3614: "# 5.5." / if identity_lost:     3627-3629: elif validation_errors: / "Syntax errors:\n"
  3706: restore_tree = not result.commit_hash   3718-3730: return, then branch -D build_branch
  3742-3748: Hebbian record when runtime has hebbian_router
src/probos/extensions/sealed_core.py: 20 _DEFAULT_SEALED_CONFIG = Path("config/sealed_modules.yaml"); 23-44 load_sealed_globs (lru_cache maxsize=1); 47-71 is_sealed_path
  31 if not target.exists(): (outside the try)   34-38 read_text + yaml.safe_load; except (yaml.YAMLError, OSError) only (Amendment A2, §17)
config/sealed_modules.yaml: 10-20 sealed_globs incl. "src/probos/substrate/**"
src/probos/config_models/agentic.py: 125-137 ExtensionsConfig; 135 enforce_sealed_core: bool = False
src/probos/config.py: 3858 class SystemConfig; 3980 extensions: ExtensionsConfig
src/probos/routers/build.py: 17 operator_checkout_refusal import; 118-187 /resolve; 417-448 _execute_build; 429 import; 446-447 llm_client / escalation_hook
src/probos/build_dispatcher.py: 40-62 __init__; 70-73 active_builds; 111-130 _try_dispatch; 138-146 _find_dispatchable; 174 _read_source_files; 191 seed; 203-205 adapter.execute; 215-222 execute_approved_build call; 270-273 reviewing; 379-418 approve/reject
src/probos/build_queue.py: 21-26 _VALID_TRANSITIONS; 150-157 has_footprint_conflict; 161-164 active_count
src/probos/build_pipeline.py: 53-54 runtime; 89-100 passes runtime=self._runtime
src/probos/runtime.py: 558 build_dispatcher annotation; 3188 self.build_dispatcher = struct.build_dispatcher; 3552 BuildPipeline(runtime=self); 4117 async def stop(self, reason="")
src/probos/startup/structural_services.py: 31-48 (config in scope); 126-130 BuildDispatcher(...)
src/probos/startup/finalize.py: 4274 runtime.pre_flight_runner = PreFlightRunner(
src/probos/cognitive/copilot_adapter.py: 269-293 _session_relative; 360-387 seed_session_directory returns session-relative keys; 798-822 scan; 838-849 base = file_contents.get(rel_path, "")
src/probos/cognitive/builder_paths.py: 49-54 ALLOWED_PATH_PREFIXES (config/ included); 207-216 refuses "..", absolute; 275-291 fix-loop roots
src/probos/worktree_manager.py: 21-28 WorktreeInfo(path, branch, build_id, created_at)
src/probos/cognitive/llm_client.py: 2675 class MockLLMClient
tests/test_ad481_extensions.py: 20-25 imports (22 SimpleNamespace, used only at 188-206); 186-211 the two _check_sealed_path tests
tests/test_bf898_fix_loop_grader_protection.py: 451-471 helpers; 626-657 the validation-raise test
tests/test_bf896_executor_identity_and_blocks.py: 1016-1045 _SeedProbe*; 1047-1087 the seed test (1085 the excerpt premise);
  28 import inspect; 701-705 the signature pin (703 parameters[-1].name == "expected_git_dir") (A1)
tests/test_ad476_specialized_builders.py: 173-176, 183-185 read `specialty` by name and default only (unaffected) (A1)
A1 dry-run tree e7fcbbe9: builder.py 3183 specialty: str = "general", 3184 expected_git_dir, 3185 enforce_sealed_core (last)
tests/test_bf904a_failed_build_restore.py: 95-170 helpers copied here; 237-246 _FakeModel; 265-270 _route_modules
tests/test_bf907_trust_identity.py: 1466-1481 boot config and _boot
DECISIONS.md: 170 BF-904a D31; 534-545 BF-901 S3 entry, 545 its Reversal; 547 next heading
PROGRESS.md: line 1 "# ProbOS Progress"; line 3 begins with S3's bold lead
A3, tree 9009b0bd (M1 after A2, then M2): builder.py 12-17 imports ast, os, stat; 1792 _write_target_key (realpath);
  1842 _HOOK_OPEN_FLAGS; 1935-1941 the hooks read (lstat S_ISREG, one open, fstat S_ISREG); 1747-1781 _restore_pre_build_files
  (1760 write_bytes, 1766-1768 exists/unlink: follow aliases, F-124); 2772-2780 _validate_python (2777 read by name);
  2791-2809 _syntax_errors (2800 is_file before the try at 2803); 3682 the 5.5 call (no root); 3766 except Exception; 3788 _git_return_to
builder_paths.py: 12 "does not follow a hard link, junction or symlink"; 197-247 builder_write_refusal (213 "..", 215 absolute, 220 ":")
security/file_access.py: 505-513 is_reparse_point; 847-876 pin_directory / read_verified_file (whole absolute chain; resolved != candidate refused)
tests: _validate_python called at test_builder_agent.py 2079-2093 and test_bf898 633-644 only; _syntax_errors called nowhere in tests/
A4, tree 495b1ac7 (M1 after A2, M2 after A3, M3): builder.py 3185-3203 _sealed_globs (3196 try; 3198 except (OSError, ValueError, RecursionError));
  3282 sealed_globs = _sealed_globs() if observe_sealed is True else () (before the executor's try at 3377)
sealed_core.py 27-28 docstring "missing or malformed (fail-open per Tier 2 log-and-degrade)"; 31 exists() outside the try; 35-36 safe_load; except (yaml.YAMLError, OSError)
routers/build.py 487 except Exception as e: (the route's BUILD_FAILURE for anything the executor lets out)
PyYAML 6.0.3 (.venv yaml/__init__.py:11) constructor.py: 235 bool_values[value.lower()] (KeyError); 241, 274 value[0] (IndexError on an empty !!int / !!float);
  288-289 value += digit*base; base *= 60 (OverflowError); 325 match.groupdict() (AttributeError when the timestamp regexp does not match)
advisory YAML loads that degrade on Exception: crew_profile.py 686-687; routers/gaps.py 34-35; experience/commands/commands_gap.py 64-65; doctor/checks/channel_slack_check.py 37-38 (telegram, matrix likewise)
setrecursionlimit: no file in *.py (S9 [deep-nesting] runs at the default limit)
```

## Absence Verified (2026-10-21)

```
CLAIM: the queue has no "approved" or "retrying" status
RUN:   read build_queue.py whole; Grep "update_status\(|\.status = \"" in build_queue.py, build_dispatcher.py
FOUND: _VALID_TRANSITIONS keys/targets queued, dispatched, building, reviewing, merged, failed; dispatcher sets dispatched,
       building, reviewing, failed, merged; cancel sets failed
HOLDS: yes

CLAIM: neither /api/build route nor the dispatcher passes runtime to execute_approved_build
RUN:   Grep "execute_approved_build\(" in src/
FOUND: build_dispatcher.py:215 (no runtime), build_pipeline.py:56/89 (runtime=self._runtime), routers/build.py:441 (no runtime)
HOLDS: yes; BuildPipeline is the one caller with a runtime

CLAIM: none of the new names exists yet
RUN:   Grep "syntax_checked|_SEALED_POLICY|def sealed_core_enforced|observe_sealed|def _sealed_globs|def _syntax_errors" builder.py;
       read build_queue.py and build_dispatcher.py whole (no _FOOTPRINT_HOLDING_STATUSES, no enforce_sealed_core)
FOUND: none
HOLDS: yes

CLAIM: no test pins "dispatched"/"building" only, _check_sealed_path, all_changed_files or the transporter path, except those updated here
RUN:   Grep "all_changed_files|_check_sealed_path|\"dispatched\", \"building\"|seed_session_directory\(tmp_dir|_LOCALIZE_THRESHOLD|transporter_complete" tests/;
       Grep "validation_errors|_validate_python|has_footprint|_normalize_change_paths" tests/
FOUND: test_ad481_extensions.py:186-211 (updated, 7.5); test_bf896_executor_identity_and_blocks.py:1058 (updated, 7.12);
       test_builder_agent.py:1443-1453 (path "a.py" resolves to itself; unaffected); test_bf898:633-645 (updated, 7.8);
       test_build_queue.py:99-111 (dispatched only; unaffected); test_builder_agent.py:2079-2093 (_validate_python unit; unaffected)
HOLDS: yes

CLAIM: (A1) no test, script or doc other than test_bf896:701-705 pins the parameter order, a default or the last parameter
       of execute_approved_build, BuildDispatcher, _check_sealed_path, seed_session_directory or BuildQueue
RUN:   Grep "inspect\.signature|getfullargspec|co_varnames|co_argcount|__defaults__|__kwdefaults__|parameters\[-1\]|\.parameters\b"
       (repository, .claude excluded; 89 files); Grep "(signature|getfullargspec|getargspec)\([^)]*(execute_approved_build|
       BuildDispatcher|_check_sealed_path|seed_session_directory|BuildQueue|has_footprint_conflict|_execute_build|_syntax_errors|
       _normalize_change_paths|perceive|\bact\b)"; Grep "(autospec|create_autospec|spec=|wraps=)" with those names in tests/;
       Grep "last parameter|optional last|last positional|positional call|positional order|parameter order|argument order";
       Grep "expected_git_dir"; Grep the five names outside src/, tests/, prompts/ (no pattern ends in $)
FOUND: test_bf896_executor_identity_and_blocks.py:701-705 (updated, 7.5b); test_ad476_specialized_builders.py:173-176, :183-185
       (by name; unaffected); test_build_dispatcher.py:144 (reads the expected_git_dir keyword; unaffected);
       prompts/archive/ad-476-specialized-builders-v1.md:971, :981 (archived); scripts/: none; docs/: prose and the
       enforce_sealed_core config field (unchanged); ui/: BuildQueueItem types
HOLDS: yes

CLAIM: no roadmap row for BF-904
RUN:   Grep "BF-904" docs/development/roadmap.md (count)
FOUND: 0
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom-API precheck, pattern 3 (`Name(`) | Capitalised calls are ProbOS symbols (`BuildResult`, `BuildSpec`, `BuildQueue`, `BuildDispatcher`, `BuildPipeline`, `BuilderAgent`, `ProbOSRuntime`, `SystemConfig`, `MockLLMClient`, `WorktreeInfo`, `CopilotBuilderAdapter`) or the precheck's own skips (`Path`, `MagicMock`, `AsyncMock`). The test doubles start with an underscore (`_Targeted`, `_FakeModel`, `_Runtime`, `_Generated`, `_VisitingProbe`); `SimpleNamespace` is imported as `_SimpleNamespace`. In SEARCH text being removed: `Field(` (pydantic's, not a ProbOS name: the note above 7.1) and `SimpleNamespace(` (the note in 7.5: the old double was a `SimpleNamespace` chain, removed). `RecursionError(` is kept in 7.8; its comment says it is not an OSError, which is the comment-only repair |
| Pattern 2 (`Name.attr`) | `BuilderAgent._LOCALIZE_THRESHOLD` and `builder_module._SEALED_POLICY` do not match (upper-case attribute, lower-case receiver); `EventType.BUILD_SUCCESS` upper-case; `SystemConfig.extensions` (removed docstring) exists |
| Field check | Keyword constructions are all existing fields: `BuildSpec(title, description, target_files)`, `BuildResult(success, spec, error)`, `WorktreeInfo(path, branch, build_id, created_at)`. `enforce_sealed_core=` is passed to functions and to `BuildDispatcher`, which is not a dataclass |
| Method check (pattern B) | `queue = BuildQueue()` uses `enqueue`, `update_status`, `has_footprint_conflict`; `dispatcher = BuildDispatcher(...)` uses `_execute_build`, `_find_dispatchable`, `reject_build`; `pipeline = BuildPipeline(...)` uses `execute_approved_build`: all exist |
| Layer import | `cognitive/builder.py` imports `extensions.sealed_core` lazily inside functions, as before; no new module-scope import. Run `tests/test_layer_boundaries.py` (M1) |
| Write census (AD-1344) | No write call is added to `execute_approved_build` or `perceive`; `seed_session_directory`'s site is unchanged. Run `tests/test_ad1344_constitution_write_refusal.py` (M2) |
| AD-1343 seam census | No `.complete(` call added; one is now skipped after a refusal. Run `tests/test_ad1343_seam_registry.py` (M2) |
| db-connect, unowned-task, store registry | none |
| config | No new field; `config/system.yaml` untouched; reads `config.extensions.enforce_sealed_core` |
| srp-size | `builder.py` grows about 60 lines; new helpers 10 to 20 lines each; test files about 330, 230 and 260 lines |
| Hidden pins | `tests/test_bf896_executor_identity_and_blocks.py:701-705`, the executor's signature pin (updated, 7.5b; found by the dry run, Amendment A1); 19 `startswith("Syntax errors")` assertions (lead kept); `test_build_dispatcher.py` constructor calls (keyword default); `tests/test_bf896_dispatcher_confinement_seam.py` executor wrappers take `**kwargs` |
| Ledger | M3 (§8) |
| Amendment A2 | 7.1's `_sealed_globs` names `OSError`, `ValueError` and `RecursionError` only in an `except` tuple, never called. S9 calls underscore helpers, `sys.getrecursionlimit` and no capitalised name; `EventType.BUILD_SUCCESS` and `EventType.BUILD_FAILURE` exist (`routers/build.py:452`, `:482`). `builder.py` grows by 14 more lines; no new module-scope import in `builder.py`; the test file gains `import sys` |
| Amendment A3 | 7.7's capitalised calls are `Path(` (skipped) and `_SyntaxReadRefused(` (underscore); `Exception`, `FileNotFoundError`, `NotADirectoryError`, `SyntaxError`, `OSError`, `ValueError` appear only as a base class or in `except`. 7.9 aliases `PermissionError` as `_Denied`; `NotImplementedError` only in `except`; 7.8's `RecursionError(` is unchanged. `builder.py` grows about 45 lines, no new import. No write call (AD-1344 census) and no `.complete(` (AD-1343) |
| Amendment A4 | 7.1's `_sealed_globs` names `MemoryError` and `Exception` only in `except` clauses, never called. 7.6 defines `class _UnlistedParserFault(Exception)` (underscore; `Exception` only as a base class), aliases `MemoryError` as `_OutOfMemory`, and calls `_parser_raising(`, `_SimpleNamespace(` and `fault(` (lower-case); `_UnlistedParserFault` is never called by name; `type[BaseException]` is an annotation. `builder.py` grows by 7 more lines, no new import; the test file gains no import. No write call, no `.complete(` |

## 13. What I could not verify here, and Prior Art

- **Not run:** no test, precheck, boot or mutation run (read-only consult). The expected strings in 7.6, 7.9 and 7.13 were derived by reading the code.
- **Host behaviour:** `fnmatch` normcases on Windows (so A7 and A8 need the named cases there) and is case-sensitive on POSIX; `os.path.normpath` keeps a leading `//` on POSIX. Documented behaviour, not run. S7's boot time is unmeasured (BF-906 and BF-907 boot the same way).
- **Live vessel:** whether the Captain's local `config/system.yaml` sets `enforce_sealed_core` (it is not read here; the field defaults to False).
- **Prior art:** skipped as ProbOS-specific plumbing with no outside analogue (a bug-fix slice); `docs/research/reference-projects.md` not consulted for overdue rows (date 2026-10-21; none examined, none updated). Internal prior work used: AD-481f (the warn-only check), BF-894 (write boundary), BF-896 (base check, seeding), BF-897 (no merge route), BF-898 (fix-loop rules), BF-904a D30, D31, D46, D48.

## 14. Diff Reviewer: properties to verify

1. With `enforce_sealed_core` off (the default, explicit False, or a runtime without that config), `execute_approved_build` reads no policy file, calls no `is_sealed_path` and logs nothing.
2. With it on, each of the four write sites logs one warning for a sealed path, naming the path with `%r`. No build is refused or changed by it.
3. The policy is `_PROJECT_ROOT/config/sealed_modules.yaml`, never a path in the work tree or relative to the working directory.
4. The resolve route still passes no runtime: pre-flight and Hebbian are unchanged there. `sealed_core_enforced` is True only for the boolean True.
5. The dispatcher's flag defaults to False and comes from `config.extensions.enforce_sealed_core` at boot.
6. Every refusal recorded anywhere still blocks the commit. Syntax is read at 5.5 for every path a write validated before (main modify, main create, repair) and for no other. No `_validate_python` call remains at write time. The error's `Syntax errors:` lead is unchanged.
7. A build holding a refusal before 4c runs no review, no targeted tests and no repair. `git_unsafe` stays False, so the cleanup runs git exactly as for any untested failed build.
8. `all_changed_files` on the first attempt equals today's list; later attempts include files the repairs created.
9. (Amendment A3) `_syntax_errors(root, paths)` reads a `.py` path only through `_work_tree_text`. Its `realpath` must lie inside `realpath(root)` (by `normcase`), else one line naming the path and `resolves outside the work tree`, and nothing is opened. A path gone or not a regular file by `lstat` is a line and is never opened. The one open uses `_HOOK_OPEN_FLAGS`, and the handle must be a regular file with the `lstat`'s identity. Every examination (`realpath`, `lstat`, open, `fstat`, read, decode, parse) is inside the `try`: `OSError` and `ValueError` become lines; `RecursionError`, `MemoryError` and anything else still reach the executor's `except Exception`.
10. `has_footprint_conflict` counts `reviewing`; `active_count` and the transitions are unchanged; `_find_dispatchable` and the dispatch mark have no await between them.
11. `perceive`'s native context and `_should_use_transporter` still read the excerpts. The seed gets whole files, and the adapter gets the mapping the seed returns.
12. `act` normalises every `transporter_complete` change; a project-relative path is unchanged.
13. No change to `builder_write_refusal`, `fix_loop_write_refusal`, the native harness route, the worktree start point or `config/system.yaml`.
14. Each updated test changes only where it pinned the old behaviour, with an inline `BF-904b (#1585)` reason; none is deleted or weakened elsewhere.
15. `execute_approved_build`'s eleven earlier parameters keep their names, order and positional-or-keyword kind; `enforce_sealed_core` follows `expected_git_dir` with default `None`. 7.5b renames its test only because the old name said "last". It still asserts `expected_git_dir`'s index and `None` default and that everything after `work_dir` is optional; it drops only the "nothing follows" clause.
16. With the flag on, a policy that cannot be read never changes a build's outcome. `_sealed_globs` returns `()` for every `Exception` the one `load_sealed_globs` call lets out except `MemoryError`, and logs one warning naming the file and the exception class: what PyYAML raises on corrupt content is an open set, so no list of classes is the contract (§19). The `except` surrounds that call only; nothing after it in the observation is guarded or needs to be, since it handles `str` values (§19's enumeration). `MemoryError` and every `BaseException` that is not an `Exception` (cancellation, interrupt, exit) still propagate. With the flag off the policy is still not read (property 1).

17. (Amendment A3) Refusals still come first; an alias refusal is one more syntax-state line after them, under the unchanged `Syntax errors:` lead. An alias that resolves inside the work tree is read: no rule stricter than the write boundary, which follows aliases. `_validate_python`, the cleanup and the return checkout are unchanged (their alias-following is F-124).

## 15. Acceptance criteria

1. (2) Both production callers give the executor the flag; `is_sealed_path` receives the repository-relative, normalised, case-folded path; a write to a sealed glob is observed with the flag on and nothing is read or logged with it off; a policy that cannot be read observes nothing, with one warning, and the build still commits (S1 to S10; A1 to A26). Every parameter the executor had keeps its name, index and kind, and the updated pin asserts it (7.5b).
2. (4) Refusals are permanent; syntax is read on the current files after the loop; `all_changed_files` is recomputed at each attempt; a build with a refusal runs no review, tests or repair; the final read refuses, unread, a path that resolves outside the work tree, and every failed examination is one `Syntax errors:` line (F1 to F8; B1 to B22; Amendment A3).
3. (6) `has_footprint_conflict` includes `reviewing`; the force-delete clause is recorded as met by BF-904a D31 (D1, D2; C1, C2).
4. (7) The visiting builder receives whole files, the excerpts serve only the native prompt context, and `transporter_complete` changes go through `_normalize_change_paths` (V1 to V3; C3 to C6).
5. Each item has a test that fails today (§6). Every mutation row is killed by the named test. One broad gate and one PR for the three milestones; the security-relevant M1 gets the cross-family Diff Reviewer, as do M2 and M3 under tier HIGH.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-10-21): the executor's signature pin

**Found by:** the orchestrator's whole-contract dry run (tree `e7fcbbe9824c460126a6430faac45fc846dfc834`, M1 to M3 applied by tool; 40 test files on the M3 state: 2,442 passed, 14 skipped, 1 failed). The failure was `tests/test_bf896_executor_identity_and_blocks.py::test_expected_git_dir_is_an_optional_last_parameter` (`:701-705`), which asserted that `expected_git_dir` is the last parameter; 7.1 adds `enforce_sealed_core` after it. §5 said "positional order unchanged". That was true of the test's purpose, not of its assertion. The absence searches covered behaviour pins and not signature pins.

**Decision.** (A) **chosen:** assert the property the test named: the eleven earlier parameters keep name, index and kind; `expected_git_dir` keeps its `None` default; the flag follows; everything after `work_dir` is optional. The test is renamed, not deleted. (B) Make the flag keyword-only: rejected; it is still last in signature order, so the old assertion still fails. (C) Put the flag before `expected_git_dir`: rejected; it changes the meaning of a positional call that passes `expected_git_dir`, which is what the pin forbids. (D) Delete or skip the pin: rejected (§14 item 14).

**Milestone.** M1, which introduces the parameter; the file joins M1's focused gate. 7.5b edits `:701-705` and 7.12 (M3) edits `:1054-1055` and `:1082-1086`: disjoint, and neither replacement contains the other's search text.

**Mutation.** A18 (`specialty` made keyword-only) is the one-line, importable signature mutant that only the pin's kind assertion kills. Rows: 36 to 37. New cases unchanged (42 in 20 functions); updated test functions 4 to 5.

**Other pins.** None that the dry run's file list would not have run (Absence Verified, A1).

**Unchanged:** D1 to D11 and every production pair; only §5's "positional order unchanged" is corrected.

## 17. Amendment A2 (2026-10-21): an unreadable policy degrades instead of aborting the build

**Found by:** the M1 Diff Reviewer, round 1 (`gpt-6.1-sol`, candidate `36e99319`, tree `ccc583a6`). With the flag on and a policy that is not UTF-8, `execute_approved_build` raised at entry (`builder.py:3188` to `_sealed_globs` `:3109` to `sealed_core.py:35`), before its `try` (`:3279`). The resolve route reported `BUILD_FAILURE` (`routers/build.py:487-493`) where the base, which never read the policy, committed. `load_sealed_globs` catches `(yaml.YAMLError, OSError)` only (`sealed_core.py:36`). P2, injected-only (the shipped policy loads), and a regression against D5. The Architect's consult had listed it as a register item without the base comparison; A2 fixes it, and it leaves the register.

**Decision.** (A) **chosen:** guard in `_sealed_globs`, M1's own function: `except (OSError, ValueError, RecursionError)`, one warning naming the file and the exception class, `()`. (B) Widen the loader's tuple: deferred. It adds AD-481f's module, a fifth production file, to M1 (§9 keeps `extensions/sealed_core.py` unchanged), and `_sealed_globs` is its only caller in `src/` besides the package re-export (`extensions/__init__.py:34`). (C) `except Exception` at entry and at each write site: rejected. After the loader every operation works on `str` and cannot raise (below), and a blanket catch would hide a defect in this code as a silent non-observation.

**What the observation can raise (CPython 3.12.13; PyYAML's pure-Python `SafeLoader`).**

| Step | Raises | Covered |
|---|---|---|
| `target.exists()` (`sealed_core.py:31`) | an `OSError` that is not a not-found kind (3.12 re-raises it) | `OSError` |
| `read_text(encoding="utf-8")` | `OSError` (the loader catches it); `UnicodeDecodeError` (a `ValueError`) | `ValueError` |
| `yaml.safe_load` | `YAMLError` subclasses (the loader catches them); on corrupt content, whatever a constructor or the composer raises: an open set, which this row first listed from source as `ValueError` and `RecursionError` only (corrected by Amendment A4, §19: executed, also `OverflowError`, `KeyError`, `IndexError`, `AttributeError`); `MemoryError` | every `Exception` but `MemoryError` (Amendment A4); `MemoryError` propagates |
| shape checks, `lru_cache`, `glob.casefold()` | nothing (safe-loaded values, `str` globs; an exception is not cached) | none needed |
| path `replace` / `os.path.normpath` / `casefold` | nothing on a `str`; the write boundary already ran `.replace` on it, and the sites are inside the executor's `try` | none needed |
| `is_sealed_path` (`fnmatch`) | nothing: `translate` escapes other characters and removes empty or reversed ranges | none needed |
| the `%r` warning | nothing (`repr` of a `str`) | none needed |

**Tests and rows.** S9 (7.6), three cases, driven through the resolve route as the reviewer reproduced it, with `_SEALED_POLICY` substituted by a scratch file. All three fail on the round-1 candidate. M1: 10 functions, 24 cases; total 45 cases in 21 functions. Rows A19 to A23: 37 to 42.

**Milestone and anchors.** M1 only. A2 edits 7.1's `_sealed_globs` REPLACE text, 7.6's file block and the prose sections (header, §3 D5, §6, §10, §11, §12, §14, §15, this section). No anchor heading, no §8 tracker pair, and no SEARCH or REPLACE text of 7.7 to 7.13 is touched. M2's pairs apply unchanged: `_sealed_globs` (`builder.py:3105`) is far from `_fix_loop_changed` (`:2783`), and M2's executor hunks start after `:3279`.

**Absence verified (2026-10-21).** Callers of `load_sealed_globs` in `src/`: `builder.py:3109` and `extensions/__init__.py:34` only. Tests that pin a raise from `_sealed_globs` or the loader: none (`tests/test_ad481_extensions.py:128-192` and the 7.6 file only).

**Unchanged:** D1 to D4, D6 to D11, every other pair; D5 gains its last sentence.

## 18. Amendment A3 (2026-10-22): the final syntax read stays inside the work tree

**Found by:** the M2 Diff Reviewer, round 1 (`gpt-6.1-sol`, M2 on the round-1 M1): NOT READY, two P2 findings, both regressions against M1. (1) Ordinary reach: `_syntax_errors` (`builder.py:2791`, tree `9009b0bd`) judged a path with `is_file()` (`:2800`), which follows links and junctions, then read it by name through `_validate_python` (`:2804`, `:2777`), with no root. A real targeted-test run that left a directory junction above the created file made the executor parse the outside file and commit (`resolved_outside: true`, `success: true`); M1, which validated each file as it was written, read the inside one. (2) Injected-only: an `OSError` from `is_file()` is raised before the `try` (`:2803-2806`), so it left `_syntax_errors` without the `Syntax errors:` lead; the executor's `except Exception` (`:3766`) still failed the build. Both hold on this tree.

**Decision.** Fix both in M2 (D12): a regression is fixed, and (1) has ordinary reach. Measured on CPython 3.12.13, Windows: `is_file()` through an ancestor junction is True; `is_symlink()` on the junction is False; `lstat` of the leaf below it is `S_ISREG`; `realpath` returns the outside path; `os.symlink` for a directory needs a privilege (WinError 1314) while `mklink /J` does not.

**How the final read can leave the work tree.**

| Route | Covered | How |
|---|---|---|
| link in place of the file | yes | `realpath` follows it; outside is refused (F7 `[leaf]`), inside is read |
| ancestor symbolic link | yes | `realpath` (F7 `[ancestor]` on POSIX) |
| ancestor junction | yes | `realpath` follows junctions (measured) (F7 `[ancestor]` on Windows) |
| junction or reparse point as the leaf | yes | a junction resolves to a directory: outside is refused, inside fails `lstat` as not regular (F6 `[directory]`); a non-link reparse file (dedup, cloud placeholder) is a regular file to `lstat` and is read |
| hard link | not an escape here | its bytes are the bytes git commits at that path, so judging them is right; the cleanup's restore writes through it (F-124) |
| `..`, absolute, drive-relative, UNC, stream, 8.3 short name | yes, twice | the write boundary refuses them (`builder_paths.py:213`, `:215`, `:220`, `_SHORT_NAME`); `realpath` plus confinement would refuse an escape anyway |
| case variant; a work tree under an alias (`/var`, a junctioned folder, SUBST) | yes | both sides resolved and `normcase`d; no false refusal |
| a `\\?\` long-path form | no false refusal | `realpath` keeps the prefix only when the unprefixed path cannot be opened, in which case the write before it failed too |
| swap between the check and the open | partly | `samestat` refuses another file opened than `lstat` saw; an ancestor swapped into an alias after `realpath` and before `lstat` is not caught: it needs a process the tests left running (F-124) |

**What the read can raise.**

| Step | Raises | Handling |
|---|---|---|
| `os.path.realpath` (non-strict, both sides) | an `OSError` 3.12 does not absorb; `ValueError` (NUL) | a line |
| `normcase`, `is_relative_to` | nothing on a `str` | none |
| `os.lstat` | `FileNotFoundError`, `NotADirectoryError` | "is no longer a regular file" |
| `os.lstat` | any other `OSError` (`PermissionError`), `ValueError` | "could not be read ..." (F8 `[stat-fails]`) |
| `open` through the opener | `OSError` (`ELOOP` for a swapped final link, `IsADirectoryError`, `EACCES`) | a line |
| `os.fstat` | `OSError` | a line |
| `read` | `OSError`; `UnicodeDecodeError` (a `ValueError`); `MemoryError` | a line; a line; propagates |
| `ast.parse` | `SyntaxError` and subclasses (NUL bytes too on 3.12) | the `line N` line |
| `ast.parse` | `ValueError` | a line |
| `ast.parse` | `RecursionError`, `MemoryError` | propagate (7.8 pins `RecursionError`) |
| any | `_SyntaxReadRefused` | its line |
| any | `BaseException` (cancellation, interrupt) | propagates |

**Tests and rows.** F6 gains `[directory]` (a guard on M2; kills B11). F7 `[ancestor, leaf]`: the outside file is valid Python, so on M2 the build commits; an `ast.parse` spy shows the outside text is never parsed. It does not assert that the outside file survives: the failed build's cleanup deletes it through the junction, on M1 and M2 alike (F-124). F8 `[stat-fails, swapped-before-open]`: the failure is injected on `os.stat` and `os.lstat` for the created path only, armed after the tests and disarmed after the read; on M2 it fails because the stat raises before the `try`. F7 and F8 (4 cases) fail on the round-1 M2 candidate. 7.8 now injects into `_python_syntax_error`. M2: 8 functions, 15 cases; total 50 cases in 23 functions. Rows: B5 and B11 rewritten, B14 to B22 added; 42 to 51.

**Milestone and anchors.** M2 only. A3 edits the `_syntax_errors` block of 7.7's first REPLACE (now four helpers and `_syntax_errors`), 7.7's 5.5 REPLACE, 7.8's lead and REPLACE, 7.9's file block, and the prose (header, §3, §6, §10, §11, §12, §14, §15, this section). No 7.7 SEARCH text changes. No anchor heading, no §8 tracker pair and no SEARCH or REPLACE text of 7.1 to 7.6 or 7.10 to 7.13 is touched. `_validate_python` is unchanged: no production caller remains, and its tests call it.

**Absence verified (2026-10-22).** Callers of `_syntax_errors` and `_validate_python` (Grep over `*.py`): `builder.py:2772`, `:2791`, `:2804`, `:3682`; `tests/test_bf898_fix_loop_grader_protection.py:633`, `:644`; `tests/test_builder_agent.py:40`, `:2079-2093`. No test calls `_syntax_errors`, and A1's signature-pin search already covered it. Tests that patch `os.path.realpath`: `test_bf896_executor_identity_and_blocks.py:917` and `test_bf904a_unapplied_blocks.py:859`, both scoped to calls that are not the executor's (unaffected). Tracked symbolic links: none (`git ls-files -s`, mode 120000).

**For the register (not fixed here).** F-124 (#1523), new evidence: a test-left junction leads `_restore_pre_build_files` (`builder.py:1766-1768`) and the return checkout to delete the outside file, on M1, M2 and A3 alike; no regression. The tests already run arbitrary code as the user, so this grants no new capability, but it is an accidental write outside the tree. In-tree aliases are read at their target, and git commits the link itself (P3). The ancestor swap race above (P3, injected-only). `_validate_python`'s four parse lines duplicate `_python_syntax_error` (P4: fold them when a 7.7 pair can be widened). §8's disclosed effects do not mention the alias refusal (P4, M3's tracker text).

**Prior art.** Kernel and library primitives exist for root-confined opens: Linux `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS)` (https://man7.org/linux/man-pages/man2/openat2.2.html) and Go's `os.Root` (https://pkg.go.dev/os#Root). Neither has a Python standard-library binding or a Windows equivalent here: considered and deferred to F-124. Not fetched (a repair amendment).

**Unchanged:** D1 to D11; D5's A2 sentence; every pair not named above.

## 19. Amendment A4 (2026-10-22): a corrupt policy of any kind degrades

**Found by:** the M1 Diff Reviewer, round 2 (`gpt-6.1-sol`, candidate `68fb9959`, CPython 3.12.13, PyYAML 6.0.3): NOT READY, one P2, injected-only, a regression against the base. Round 1's non-UTF-8 failure is resolved. A2's guard (`except (OSError, ValueError, RecursionError)`, `builder.py:3198` on tree `495b1ac7`) does not cover four classes that PyYAML's pure-Python constructors raise from policy contents, none of them a `YAMLError`. A sexagesimal float of 180 parts raises `OverflowError` (`constructor.py:288-289`); `!!bool neither` raises `KeyError` (`:235`); an empty `!!int` raises `IndexError` (`:241`); `!!timestamp never` raises `AttributeError` (`:325`). Each escapes the loader (`sealed_core.py:36`) and the guard before the executor's `try` (`:3282` against `:3377`), and the resolve route reports `BUILD_FAILURE` for an unsealed path (`routers/build.py:487`). On base `d09e67d1` the build commits. The orchestrator's fuzz (14 tags, 80 bodies, 3 placements) found `AttributeError`, `IndexError`, `KeyError` and `ValueError` outside `YAMLError` and did not generate the `OverflowError` case: the set is open.

**Decision.** Fix in M1 (a regression). (B) **chosen:** `except MemoryError: raise`, then `except Exception` around the one `load_sealed_globs` call: one warning naming the file and the class, `()`. This is Tier 2 log-and-degrade, as the loader's docstring promises (`sealed_core.py:27-28`) and as other advisory YAML loads do (`crew_profile.py:686-687`, `routers/gaps.py:34-35`, `commands_gap.py:64-65`, `channel_slack_check.py:37-38`). (D) B plus a hardened loader: deferred (R1). It adds AD-481f's module as a fifth production file, and its `lru_cache` would cache `()` for a corrupt file, so a repaired policy would stay unobserved until a restart. (C) The hardened loader alone: rejected for the same reasons, and the existence check still needs this guard. (A) The reviewer's closed list of seven classes: rejected. A closed list against an open set misses the next class (the fuzz missed one; a later PyYAML can add one). A2's (C) stands: its premise, that every step after the loader works on `str`, was verified by execution (119 matcher calls on malformed, Unicode and long patterns raised nothing). What A4 corrects is A2's enumeration of the loader step, which was read from source as a closed list. The catch is one call wide and not silent, and S1 to S8 run the real loader on the real policy, so a defect in the loader still fails a test.

**What the observation can raise, from the policy lookup to the last matcher call.**

| Step | Raises | Handled |
|---|---|---|
| `sealed_core_enforced(runtime)` | `AttributeError` | caught there (False) |
| the lazy import of `load_sealed_globs` | `ImportError` (a code defect, not the file) | propagates (outside the `try`, as before) |
| `str(_SEALED_POLICY)`, the `lru_cache` key, `Path(config_path)` | nothing on a `str` | none needed |
| `target.exists()` | an `OSError` 3.12 does not absorb | the guard |
| `read_text(encoding="utf-8")` | `OSError` (the loader); `UnicodeDecodeError` (S9 `[not-utf-8]`); `MemoryError` | the loader; the guard; propagates |
| `yaml.safe_load` | `YAMLError` (the loader); on corrupt content an open set: executed so far `ValueError`, `OverflowError`, `KeyError`, `IndexError`, `AttributeError`, `RecursionError`; `MemoryError` | the loader; the guard, by class-independence (S9 `[unlisted-class]` pins it); propagates (S10) |
| shape checks, `raw.get`, `str(g)` for a `str` | nothing: `SafeLoader` builds plain `dict`, `list`, `str` (an unhashable key is a `ConstructorError`, a `YAMLError`) | none needed |
| `_check_sealed_path`: `normpath`, `/` separators, `casefold` | nothing on a `str` (verified by execution) | none needed; inside the executor's `try` anyway |
| `is_sealed_path` (`fnmatch.translate`, `re` compile, `startswith`) | nothing: `translate` escapes and drops empty or reversed ranges, and there is no counted repetition (119 calls executed, long patterns included) | none needed |
| the `%r` warning | nothing (`logging` handles a formatting error itself) | none needed |
| any | `BaseException` that is not an `Exception` (cancellation, interrupt, exit) | propagates |

`RecursionError` is caught: corrupt content causes it, and the stack has unwound to `_sealed_globs`'s frame before the handler runs. `MemoryError` propagates, and the route's own handler fails the build, as on the base. An out-of-memory process should fail the build, not quietly lose a governance observation.

**Tests and rows.** S9 grows from 3 to 8 cases. `[overflow, unknown-bool, empty-int, bad-timestamp]` are real policies (the reviewer's texts, after a valid globs head). `[unlisted-class]` replaces the loader module's `yaml` with a namespace whose `safe_load` raises `_UnlistedParserFault` and kills the closed-list mutant A20. Each case's class is asserted, so a case that a later PyYAML turns into a `YAMLError` fails as a premise. S10 (new) pins that `MemoryError` propagates. On the round-2 candidate, the five new S9 cases fail (`BUILD_FAILURE`) and S10 passes (a guard). `[deep-nesting]` stays sized by `sys.getrecursionlimit()`. A fixed depth would stop raising `RecursionError` if the limit were raised, and nothing in `src/` or `tests/` raises it. Its cost (about 1.7 s, quadratic scan) is accepted. M1: 11 functions, 30 cases; total 56 cases in 24 functions. Rows: A19 and A20 rewritten, A24 to A26 added; 51 to 54. Lines without a row: the docstring.

**Milestone and anchors.** M1 only. A4 edits 7.1's `_sealed_globs` REPLACE text, 7.6's file block, and the prose (header, §3 D5, §6, §10, §11, §12, §14, §15, §17's `yaml.safe_load` row, this section). It does not touch any anchor heading, any §8 tracker pair, or any SEARCH or REPLACE text of 7.5, 7.5b or 7.7 to 7.13. No text in 7.7 to 7.13 names the sealed policy, so no M2 or M3 SEARCH contains a line A4 changes. `builder.py` grows by 7 lines above M2's hunks; the pairs are matched by text, not by line.

**Absence verified (2026-10-22).** `_sealed_globs|load_sealed_globs` over `*.py`: `builder.py:3185-3282`, `extensions/__init__.py:19, 34, 42`, `sealed_core.py:24, 55`, `tests/test_ad481_extensions.py:31-192` and the 7.6 file. No test pins a raise from either or patches the loader module's `yaml`. `except MemoryError` in `builder.py`: none before A4, so A24 and A26's line is unique. `setrecursionlimit` in `*.py`: none.

**For the register (not fixed here).** R1 (P3, injected-only): the loader's own tuple (`sealed_core.py:36`) is narrower than its docstring, and its other consumers (`is_sealed_path(None)` at `:55`, the package export at `extensions/__init__.py:34`) still let a corrupt-scalar class out. New evidence: the set is open. The loader caches `()` for a `YAMLError` but nothing for a raised class (P4, inconsistent caching). An unreadable policy is re-read and re-parsed for each flagged build (P4, about 0.3 ms to 330 ms, accepted). The warning carries the class but not the traceback (P4, diagnosability).

**Prior art.** Skipped: a repair amendment with no outside design question.

**Unchanged:** D1 to D4, D6 to D12; every pair not named above; D5 gains the open set.

## 20. Validation of record (2026-10-22, win32)

Written by the orchestrator after the build, from the campaign's own output. It records what was run on the tree that ships; it changes no decision.

**Review history.** M1: round 1 NOT READY (one P2, a non-UTF-8 policy aborted the build; Amendment A2), round 2 NOT READY (one P2, four more PyYAML constructor classes escaped the guard; Amendment A4), round 3 READY. M2: round 1 NOT READY (two P2s in the final syntax read; Amendment A3), round 2 READY. M3: round 1 READY. Every round by `gpt-6.1-sol` on CPython 3.12.13; round 1 of M1 ran on CPython 3.14.3 and every later brief named the project's interpreter.

**Mutation campaign.** The 54 rows of section 10 ran one at a time, in four groups on four checkouts of one tree: A (25 rows) against `tests/test_bf904b_sealed_core_observation.py`, unmutated baseline 30 passed; B (22 rows) against `tests/test_bf904b_fix_loop_state.py` and `tests/test_bf898_fix_loop_grader_protection.py`, baseline 120 passed, 1 skipped; C (6 rows) against `tests/test_bf904b_dispatch_and_visiting.py`, baseline 11 passed; A18 against its named signature pin alone, baseline 1 passed. Each row was restored before the next, on tree `14c4e021fd9af020abf451e7af21e2a61ca846d4` (commit `77b3e5ac`: the batch's code and tests as committed; the commits after it change documents only). **54 of 54 killed.** First failing test per row: A1 and A13 `the_resolve_route_passes_the_runtime_flag[flag-on]`; A2, A3 and A9 `a_write_to_a_sealed_path_is_observed_at_each_write_site[modify]`; A4 and A6 `with_the_flag_off_no_policy_is_read_and_nothing_is_logged[off]`; A5 `the_policy_is_this_probos_file_not_the_work_tree_or_the_working_directory`; A7 `spellings_of_a_sealed_path_are_observed_and_others_are_not[dot-and-double-slash]`; A8 `a_glob_is_matched_without_regard_to_case[directory-itself]`; A10 `a_write_to_a_sealed_path_is_observed_at_each_write_site[create]`; A11 `a_write_to_a_sealed_path_is_observed_at_each_write_site[repair-modify]`; A12 `a_write_to_a_sealed_path_is_observed_at_each_write_site[repair-create]`; A14, A15 and A16 `the_dispatcher_hands_its_flag_to_the_executor[on]`; A17 `a_real_boot_wires_the_config_flag_into_the_dispatcher`; A18 `expected_git_dir_keeps_its_position_and_only_optional_parameters_follow_it`; A19 `a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits[overflow]`; A20 `a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits[unlisted-class]`; A21, A22 and A23 `a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits[not-utf-8]`; A24 `a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits[deep-nesting]`; A25 and A26 `running_out_of_memory_while_loading_the_policy_still_propagates`; B1 `a_syntax_error_still_there_after_the_loop_blocks_the_commit[main-modify]`; B2, B5, B7, B8, B13 and B21 `a_syntax_error_still_there_after_the_loop_blocks_the_commit[main-create]`; B3 `a_syntax_error_still_there_after_the_loop_blocks_the_commit[repair]`; B4 `a_file_a_repair_creates_is_targeted_on_the_next_attempt`; B6 `a_refusal_blocks_the_commit_whatever_the_syntax_state`; B9 and B10 `a_build_with_a_refusal_runs_no_tests_review_or_repair`; B11 `the_syntax_state_is_read_from_the_files_the_tests_left[directory]`; B12 `the_syntax_state_is_read_from_the_files_the_tests_left[undecodable]`; B14, B15 and B16 `an_alias_the_tests_leave_is_refused_and_its_target_never_parsed[ancestor]`; B17 and B20 `the_syntax_state_is_read_from_the_files_the_tests_left[deleted]`; B18, B19 and B22 `a_file_that_cannot_be_examined_after_the_tests_is_one_syntax_line[swapped-before-open]`; C1 and C2 `a_build_in_review_holds_its_files`; C3, C4 and C5 `the_visiting_builder_is_seeded_with_whole_files`; C6 `transporter_changes_get_project_relative_paths[transporter]`. Where the first failing test is not the one the contract names, the named test was run alone against the mutant and killed it: B20 `an_alias_the_tests_leave_is_refused_and_its_target_never_parsed[ancestor]`. Every other row was killed first by the test the contract names. sha256 of that tree's working copies (the same on every checkout): `src/probos/build_dispatcher.py` `a6f8c05e8ca82f2c3f2aad7c758297984d375d4dd2f550810e591da8ef5ad0c8`, `src/probos/build_queue.py` `64db80ed812a507a19222882e9c02bf43fc2f1861386ee436673f43f99f911d1`, `src/probos/cognitive/builder.py` `421256211a331339b95c4cb1bf2fd296719363bee08ba1c64c43254585e5d9b7`, `src/probos/routers/build.py` `2fae1d55ca9ebbbd4c26d08b7a58c2dd374d60921c7bba9471d5be206a023314`, `src/probos/startup/structural_services.py` `0956d566f1127d51a1cf07bbcd239c515caff100f9ad909b2911ef0799544197`, `tests/test_bf896_executor_identity_and_blocks.py` `22c7df7763f463e0e3d80d0238365787724fd21b492311bc7c9a59fc89bf8905`, `tests/test_bf898_fix_loop_grader_protection.py` `9b166af954b75597be01c838d3419d33fd1e9ffc8c67466223602ba78e1cacaf`, `tests/test_bf904b_dispatch_and_visiting.py` `700c3de4ce5c2af01b77fe9cc8e208bd638649fbc0bfd875532328fea1abd48c`, `tests/test_bf904b_fix_loop_state.py` `82323eea59c9864706b5ed2d63d11d78d7a6161834ec593d8e1bb9af9e627d64`, `tests/test_bf904b_sealed_core_observation.py` `b37cbc0c5e58596a720f29e05f62b3ae547bea997ffd547280446cafd1b6c71d`.

**Consolidated focused checks** (the test files that name a changed surface, scrubbed environment at `-n 8`, then eight files unscrubbed at `-n 0`): M1's frozen candidate 2,431 passed, 14 skipped, 0 failed (257 passed, 3 skipped unscrubbed); M2's 2,438 passed, 15 skipped, 1 failed (an unrelated lifecycle-test flake, recorded as F-271; its whole file reran 261 passed) (265 passed, 4 skipped unscrubbed); M3's 2,450 passed, 15 skipped, 0 failed (276 passed, 4 skipped unscrubbed); the scratch state of the final contract 2,456 passed, 15 skipped, 0 failed (282 passed, 4 skipped unscrubbed). The broad gate's receipt and CI are recorded on #1585, not here.

**Register.** F-254 to F-271 and new evidence for F-124 are on #1523 (comment 6335584748).
