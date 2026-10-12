# AD-1240 — Workspace tool-result offload with hourly generation retention (#1239)

**Offload large tool results to the agent's workspace. Retire them in whole hourly generations that ProbOS's own writers cannot race. Rebuild from the preserved candidate onto current `main`.**

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-11
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-11 (Calls 3 and 4; Call 5 consolidation; Call 6 rulings, written in by Call 7)
**Revised by:** `claude-architect`, Call 10 (2026-10-12)
**Issue:** [#1239](https://github.com/seangalliher/ProbOS/issues/1239). The Captain's revised contract is comment 6 (2026-10-11).
**AD number:** AD-1240 was already allocated to #1239, so `scripts/ad_ceiling.py` was not run, and this contract allocates nothing.
**Base:** `origin/main` `1c9abde5bcde5fef96f2035ff319f81b0c002ff9`.
**Preserved candidate:** local ref `refs/preserved/ordinary-1239-e38710b8`:
- commit `5f7c7c591215d9eee773440257b6783a16fb6949`
- tree `e38710b8c6691f0c3c7ab70dea4546af410d4233`
- base `0ae79d95a1746d91e03f5ceb59b5b6d75600c735`

**Status:** Ready for the Builder, milestone by milestone (M0–M5).
**Risk:** High. This code deletes files, and it must never lose ProbOS data before its retention expires.
**Estimated new or ported test cases:** about 90 to 120 parametrized cases across the three AD-1240 test files. Report the counts you actually collect.

---

## Revision 1 (2026-10-11): rulings from Architect Calls 3 and 4

Call 3 triaged M1. Call 4 ruled on the round-1 Diff Reviewer report (`logs/review-m1-round1.txt`). Each ruling is binding and is written into the section named in the last column. Where a later ruling replaces an earlier one, the earlier one is listed as superseded.

| Ruling | What it says | Why | Where |
|---|---|---|---|
| D1 | An entry inside an expired generation that the pinned primitives refuse (a link, a special file, or a name they reject) is `skipped` and keeps its generation on disk. It never latches | Only a process outside ProbOS can create such entries. A bounded remover for them would be a new removal primitive | §3.4, §9, §10 |
| D2 | `file_access.py` gains one public wrapper, `is_reparse_point`, around `_is_reparse`. The store imports the wrapper | The Engineering Principles forbid importing another module's private names | §2 row 14, §3.4, §7 row 12 |
| D3 | When `publish_file` raises, the artifact counts as committed only if `manifest.json` holds exactly the staged bytes. Otherwise the error is re-raised. Removing the staged file afterwards uses the retry policy | No manifest other than the staged one can be advertised | §3.2, §10 (fsync residual) |
| D4 | Cached identities (and, after F2, registry entries) under a generation are evicted when its removal **starts** | A generation being removed is already unreadable by name. Nothing publishes into it | §3.4 |
| D5 | The retry runner never sleeps past the per-sweep budget | Stricter than "stop after the budget is reached", and allowed by §3.5 | §3.5 |
| Call 3 repair 1 | Refuse a caller-supplied `now` that is ahead of the store clock | — | **Superseded by F1**: the parameter is removed |
| Call 3 repair 2 | Only a *transient* deferral escalates at 2R. Cap deferral and foreign entries never escalate | Otherwise an outsider who plants entries could latch publication | §3.6, §1 (`test_cap_deferral_and_foreign_entries_never_escalate`), §7 row 17 |
| Call 3 repair 3 | The public `is_reparse_point` | Same as D2 | §2 row 14 |
| Call 3 repair 4 | `_settle` checks a chain before classifying the failure | The check now uses the anchor chain (F3), not the parent's | §3.4 |
| Call 3 repair 5 | A namespace-level transient deferral is logged at WARNING | It now also escalates (F5) | §3.5, §3.6 |
| Call 3 first-CI note | The POSIX-premise tests run for the first time on `ubuntu-latest` and must show PASSED there. The reserved-name cases assert their premise | No Linux runner exists on the Captain's machine | §4.M5, §1 |
| F1 | `reap_tool_results()` takes **no argument** anywhere. The sweep reads its time from the store clock inside the lock | A `now` validated before the lock let a queued sweep delete a commit 24 h early | §3.6, §4.M1, §4.M4, §1 |
| F2 | An in-process registry, `CommittedArtifacts`, is cross-checked on every read. After a restart the read falls back to the manifest-consistency check (a documented residual). The guarantee sentence is corrected | A consistent rewrite, or a changed `committed_at`, was being served | §3.3, §3.10, §1, §9, §10 |
| F3 | `_settle` checks the **anchor** chain (root → owner → `.tool-results`). A change at or below `<GEN>` while the anchor is intact is foreign | A sound parent proves nothing about a child, and a change above the generation must latch | §3.4, §1 |
| F4 | POSIX removal is confined to directory objects, not pathnames. This is documented, with a POSIX-only test | Closing the window needs the isolation the Captain declined | §3.4, §9, §10, §1 |
| F5 | Root and namespace pins and listings go through the retry runner. An exhausted transient defers with a WARNING, and escalates to `failed` after one retention period of continuous deferral | A brief transient at the root was latching publication | §3.5, §3.6, §1, §7 rows 20–21 |
| F6 | N5 asserts that the identity cache was populated under the generation before it asserts eviction | The test passed with an empty cache | §1 N5 |
| F7 | The sweep's deferral log line states availability from the actual latch state | The line said "enabled" after the store had latched | §3.6 |
| M2 cost | The ordinary walk uses `os.scandir` with no-follow `lstat`. A plain regular file needs no `resolve`. Directories and links are resolved once each. The R2-5 bounds are new | Resolving every entry made the overview about 6× slower and protected nothing | §4.M2, §1 R2-5, §3.11, §7 rows 22–23 |
| M1 round 2 (Builder, accepted) | The registry record carries a seventh field, `representation` | Without it, flipping only the manifest's representation went undetected | §3.10, §7 row 18 |

**Call 6 rulings** (on the M4a and M4b integration findings). They are prefixed `C6-` because the Call 3 table above already uses D1–D5.

| Ruling | What it says | Why | Where |
|---|---|---|---|
| C6-D1 | AD-1192 owned-steps pages stay inline. They are identified by a producer-owned typed result, `OwnedStepsViewResult(ToolResult)`, returned only by `ReadOwnedStepsTool`'s success path. `_prepare_result` exempts it like `WorkPullReceipt`. No general "complete-by-contract" rule, and no threshold change | Owned-steps authority requires the exact page text in `PresentedToolResult`, and an offloaded page could never be acknowledged. The producer already caps a page at 16 KiB | §3.12, §1, §2 row 28, §7 rows 24–25 |
| C6-D2 | `delivery_remaining` is the minimum of the total ceiling (minus AD-1324 redo calls) and, when AD-1208 is armed, the counted ceiling | With only `max_iter - iteration`, a tier-1-inflated `iteration` refused recovery that was possible, and a near-cap counted budget allowed recovery that was not | §3.9a, §1, §4.M4, §7 rows 26–27 |
| C6-D3 | `test_ad1191_delegation_wire.py`: apply candidate blob `c28c082f` verbatim. `test_ad1320_agentic_budget_awareness.py:615`: move its `native_builder.py` blob pin, **last**, with an inline reason | `main`'s ad1191 equals the candidate base. The pin must follow a required edit, but only after the file is frozen | §2 rows 24 and 29, §4.M5 |
| C6-D4.1 | The shutdown store stop sits in a `finally` inside the existing pools step. The BF-882 pins are not extended | It still stops the store if the pool helper raises, and it needs no new guarded step | §2 row 17, §1, §4.M4 |
| C6-D4.2 | Phase 1 starts the store **after `trust_network.start()` and before the identity registry** | A failure or cancellation inside `store.start()` otherwise left the identity registry's connection open. Main's unwind stays byte-identical apart from the store stop | §2 row 15, §1, §4.M4, §10 |
| C6-D4.3 | `""`, `"."` and `Path()` count as a missing root | `WorkspaceManager` would otherwise resolve them to the platform data directory, which is ambient storage | §4.M4 |
| C6-D5 | Armed-unavailable stays the policy. A test that fails because of it may get one pre-authorised minimal adaptation (R-a); every other case is a hard stop | The ratified rule is that missing production ownership never silently chooses legacy. Each adapted file is recorded | §1, §2 rows 30+, §6, §10 |
| C6 small | The constructor keyword `workspace_results=` goes last and is assigned through the slot, guarded by `is not None`. M4a's two equivalent mutants are accepted, on one condition: the forged-view test asserts the exact error code and `stopped_reason` | — | §4.M4 |

---

## Revision 2 (2026-10-12): rulings from Calls 8, 9 and 10 and the review-3 repairs

Call 8 ruled on delivery findings F1 and F2 (`logs/architect/1239-call8.out.txt`); Call 9 ruled on reaper findings A1-1 to A1-6 (`logs/architect/1239-call9.out.txt`); the walk findings were repaired by Builder A2 (`logs/builder-a2-repair-report.txt`); Call 10 transcribed all of it, with the orchestrator's corrections from checking M5a. Where a Builder's report differs from a ruling, the report's anchors, counts and killing tests are used and the difference is said in place. Rulings prefixed `C8-` and `C9-` to keep them apart from Revision 1's F1–F7.

| Ruling | What it says | Where |
|---|---|---|
| C8-F1 | When delivery is armed, the recovery reader `read_file` is offered full in the AD-1189 manifest (`keep_full`), so the deferred-schema guard never refuses the reader a worked call advertises. Plan mode whose AD-1156 allowlist excludes `read_file` keeps legacy delivery, with one INFO log | §3.8, §3.13, §7 rows 28 and 32, §10 |
| C8-F2 | An artifact path this run published is a run-local workspace promise (`reserve_workspace` / `workspace_promised` on `SourceRecoveryScope`, 6 → 8 methods). A call naming it is validated against the reader admitted at first admission before invocation, and only `read_file` may serve it. The alias check is decided outside `invocation_context`'s `try` (Builder deviation, accepted: inside it a refusal was swallowed into a fresh read) | §3.9, §3.13, §7 rows 29–31 |
| C8 residual | A failed recovery read through a reader not in the dispatch offer is labelled unknown in AD-1248 failure summaries | §9 note, §10 |
| C9 A1-1 | The guarantee is narrowed to what one clock sample per sweep can promise. No code change | §3.6 item 4, §9, §10 |
| C9 A1-2 | Identities under an expired generation are evicted when its removal starts; its `CommittedArtifacts` bucket only when the generation is removed whole or found already gone | §3.4, §3.10, §7 rows 35–36 |
| C9 A1-3 | A root or namespace this process has pinned before (`DirectoryIdentities.knows`) that is now missing is an integrity failure; one never created, or not remembered after a restart, is a healthy empty sweep | §3.4, §3.5, §9, §7 rows 37–38 |
| C9 A1-4 | A capped sweep resumes, through a rotating cursor (`_rotated`, `_capped_at`), after the owner and generation where its entry budget ran out. Residual only inside one generation | §3.4, §9, §10, §7 rows 39–40 |
| C9 A1-5 | The climb probe, the root pin with its listing and the namespace pin with its listing each retry as one unit, closing check included; the closing check of the pin removal ran under is not retried | §3.5, §7 rows 21, 41–42 |
| C9 A1-6 | "What it buys" names the compared fields; manifest keys the record does not hold are not compared; the identity sentence is restated; the registry estimate is 0.75 KB per entry | §3.10, §9, §10 |
| A2 walk | The ordinary walk observes a directory with `lstat` (no-follow) before and after its scan and enters only a real, non-reparse directory with the expected identity; a link to a directory is listed once and never entered or sized. Residual: only the directory's own final component is observed | §3.11, §9, §7 rows 22–23, 33–34 |
| C10 corrections | Two cached identities per published generation, not one; the cross-process margin is `end(G) − committed_at`, so two processes on one root are not promised; the latch list is completed; 15 POSIX-skipped cases in 8 test functions at M5a, not ten (20 cases in 10 functions after the repairs); a rendered owned-steps page can reach about 16.8 KB; a permission-class error while removing an expired generation latches (a decision the Captain can change) | §3.4, §3.6, §9, §10, Prior Art |
| R4 delivery | `_promised_context` compares the reader's resolved target with the lexically normalized spelling (`os.path.normpath`) that `workspace_promised` selected the promise by, so an equivalent spelling recovers through the unchanged reader. The crew verifier's session-correction projection carries no workspace store, so it is armed-unavailable by construction (unchanged from the base) | §3.13, §7 rows 31 and 43, §10 |
| R4 walk | `_children` classifies a child from the observation it carries (`_classify`), including the second, identity-bearing `lstat` of a real directory, so a stat and the link flag (and, for a non-link, the kind) never disagree; the kind of a link's target still comes from the scan entry (`entry.is_dir()`) and may be cached from the scan | §3.11 item 5a, §7 row 44 |
| R4 wording | The commitment comparison holds while the process holds the artifact's record (not for the whole process lifetime); the cursor is dropped when a directory's pass completes below the shared cap, and a deferred pass keeps it; a non-transient failure to list the root raises `workspace_reap_failed` (latches) instead of returning a failed tally, while a transient one returns a `deferred` tally and, held for one retention period, a `failed` tally (latches); records of generations that an outside process removes stay in memory; the lock-hold at 10,000 entries was measured from about 10 s to over 35 s depending on the host's load, and is not a bound | §3.4, §3.10, §9 |

---

## 0. Read first, and the standing rules

1. Read `.github/copilot-instructions.md`. It applies in full.
2. Read issue #1239: the body and all six comments.
3. **Do not run anything in `D:\ProbOS-worktrees\ordinary-1239-20260918-d2b4d869`, and do not edit anything there.** Read the candidate only through git objects:
   ```
   git show refs/preserved/ordinary-1239-e38710b8:<path>
   git diff 0ae79d95a1746d91e03f5ceb59b5b6d75600c735 refs/preserved/ordinary-1239-e38710b8 -- <path>
   ```
4. **Never use `git apply --3way`, cherry-pick or a textual merge** for any path that §2 marks *fresh edit*. Main has rewritten those regions.
5. The prior-review probes are in this worktree, gitignored:
   - `logs/probes/probe_1239_review_r1.py` (9 cases)
   - `logs/probes/probe_1239_review_r2.py` (5 cases)

   Read them in place. They are **defect-positive**: each one passes on the rejected candidate. Port every case that §1 marks REQUIREMENT into its named acceptance test, inverted so it asserts the fixed behaviour. Each ported test must **assert its premise first**, so it fails loudly if its setup did not reach the boundary under test.
6. **Import root.** The editable install points at `D:\ProbOS\src`. Every focused command must set `PYTHONPATH` to this worktree's `src` and check the import root first:
   ```powershell
   $env:PYTHONPATH = "<this-worktree>\src"
   d:/ProbOS/.venv/Scripts/python.exe -c "import probos, pathlib; p = pathlib.Path(probos.__file__).resolve(); print(p); assert '<this-worktree-name>' in str(p)"
   d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:cacheprovider
   ```
   The AD-1240 test files keep the candidate's `_assert_provenance()` session fixture. Its `_ROOT` is this worktree, and it asserts that every loaded `probos.*` module lives under `_ROOT / "src"`.
7. **Platforms.** CI runs on `ubuntu-latest`; the canonical gate and the Captain run Windows. Two rules:
   - A test whose premise needs a Windows handle, a `winerror`, a junction or a drive letter is marked `@pytest.mark.skipif(sys.platform != "win32", reason="AD-1240: <premise> is Windows-only")`. It is **paired** with an injected-remover or injected-error variant that runs on both platforms.
   - A test that needs a POSIX premise (`EBUSY`, a symlink without privilege, `/` as the anchor) gets the mirror skip, `sys.platform == "win32"`, plus its own paired injected variant.

   A test may never skip on both platforms.
8. **No broad gate.** The orchestrator runs the single receipted gate once, after review. Run only the focused lists below.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 1. The Captain's revised contract, and the acceptance set it implies

**Contract (comment 6).**
- `.tool-results` is a runtime-reserved directory whose contents may be removed once their retention has expired.
- ProbOS no longer preserves data that a process outside ProbOS writes or substitutes inside it.
- Everything else stands:
  - offloads read back exactly;
  - data produced inside ProbOS is never lost before its retention expires;
  - the private-path, foreign-owner and expiry protections from R1 remain.

**Orchestrator rulings (Call 2):**
- **C1.** Tier-1 `run_python` counts as "outside ProbOS" for this contract. `code_runner.py:489` runs Tier-1 code with the owner's workspace as its working directory, and `workspace.py:18` says that boundary is "confinement-by-convention, not a kernel-enforced boundary". Add no claim and no protection beyond what this design delivers.
- **The 2R latch escalation** is adopted. It is reversible: a later decision can change it to "warn only" (see §3.6).

| ID | Disposition | Acceptance test (file :: name) | Premise asserted first → required outcome | Ported from |
|---|---|---|---|---|
| R1-1 | REQUIREMENT | `test_ad1240_tool_result_delivery.py::test_promised_source_alias_refuses[structured]` (plus a physical-alias case: Windows junction / POSIX symlink, each with a mirror skip) | **Premise:** the worked call was emitted with the exact promised absolute path, and the resolver was then redirected (physical case: `Path(p).resolve() != original`). **Outcome:** `stopped_reason == "error"` and `error == "source_changed"`; exactly 2 LLM requests; the replacement sentinel appears in no request; `.tool-results` does not exist | probe R1 `test_parent_r1_source_alias_downgrades_recovery` |
| R1-2 | REQUIREMENT | `test_ad1240_workspace_results.py::test_legacy_routes_refuse_reserved_namespace` | **Premise:** a real publication for agent B; A and B have the same `owner_key` but different `owner_digest`; the typed reader refuses A with `workspace_owner_invalid`. **Outcome:** the real GET, file POST, suggestion list and suggestion create all return 400 at three clocks: `committed_at`, `committed_at + R`, and `generation_expiry − 1`. The governed-write AsyncMock is never awaited. The suggestion store is unchanged. `list_files` and `total_bytes` exclude the namespace. Dismiss-by-id still works | probe R1 `test_parent_r1_legacy_http_reads_foreign_expired_and_accepts_write` |
| R1-3 | REQUIREMENT | `test_ad1240_workspace_result_lifecycle.py::test_missing_anchor_terminates` (Windows: a real unavailable drive) plus `…_injected` (both platforms: a stubbed pin raises `FileNotFoundError` at an anchor whose `parent == self`) | **Premise:** `anchor.parent == anchor` and `anchor.stat()` raises `FileNotFoundError` (real on Windows, stubbed in the injected case). **Outcome:** `WorkspaceResultError("workspace_reap_failed")`; the anchor is visited at most once; nothing is created; the Phase-1 owner stays `UnavailableWorkspaceResults` | probe R1 `test_parent_r1_missing_anchor_repeats_until_bounded_probe_aborts` (repoint its monkeypatch target to the new module) |
| R1-4 | REQUIREMENT | `test_ad1240_tool_result_delivery.py::test_fresh_read_errors_keep_producer_semantics[reader × structured]` | **Premise:** the argument is an existing directory, and no promise exists. **Outcome:** armed and unarmed runs both end `complete` with 2 requests; the correction is consumed; there is one `is_error` result | probe R1 `test_parent_r1_fresh_directory_error_changes_loop_contract` (×4) |
| R1-5 | CHANGED SHAPE (integrity latches, transients defer) | (a) `test_ad1240_workspace_result_lifecycle.py::test_integrity_failure_latches_publication` | **Premise:** a real integrity cause. The pinned `.tool-results` directory (or the owner directory) is replaced by a junction or symlink between sweeps, and the identity cache holds its old identity; mirror skips plus an injected `FileAccessDenied` variant; and the probe's stubbed `failed=1`. **Outcome:** `store_tool_result` raises `workspace_unavailable`; a later clean public sweep does not clear the latch; a completed `stop()` then a successful `start()` clears it | probe R1 `test_parent_r1_failed_sweep_still_publishes` |
| | | (b) `…::test_sharing_violation_defers_without_latch` (Windows: a real handle opened without `FILE_SHARE_DELETE`) plus `…_injected` (both platforms: the remover raises `OSError(errno.EBUSY)`, and on Windows `PermissionError` with winerror 32) | **Premise:** a direct `os.remove` of the held file raises `PermissionError` with `winerror == 32` (Windows real case). **Outcome:** `deferred == 1`, `failed == 0`; injected sleep total ≤ 2.0 s; publication is still admitted. After the handle is closed, the next sweep gives `deleted == 1` | new; replaces the candidate's `test_r1_real_filesystem_retention_failure_latches_publication` |
| | | (c) `…::test_persistent_deferral_escalates_at_two_retention_periods` | **Premise:** a generation stays deferred across sweeps because of a *transient* failure. **Outcome:** at `now < end(G) + 2R` it is still `deferred` with no latch; at `now >= end(G) + 2R` it counts as `failed` and latches | new |
| | | (d) `…::test_cap_deferral_and_foreign_entries_never_escalate` (Call 3 repair 2) | **Premise:** the clock is at `end(G) + 2R`; `SWEEP_ENTRY_CAP` is patched to 3; a second expired generation holds only entries the primitives refuse. **Outcome:** the capped generation gives `deferred >= 1`, `failed == 0`; the foreign-only generation gives `skipped >= 1`, `failed == 0`; publication is admitted | new |
| | | (e) `…::test_root_transient_defers_without_latch` (F5), injected on both platforms | **Premise:** `pin_directory(root)` raises an error that `classify_os_error` labels transient (`PermissionError` with winerror 32 on Windows, `OSError(errno.EBUSY)` on POSIX). **Outcome:** recorded sleeps are `[0.05, 0.2, 0.5]`; `deferred == 1`, `failed == 0`; a WARNING is logged; publication is admitted. The same holds for the namespace pin and listing | ported from the reviewer's `root-transient` probe |
| | | (f) `…::test_persistent_root_deferral_escalates_after_one_retention_period` (F5) | **Premise:** the same root (and, as a second case, namespace) transient persists across sweeps. **Outcome:** at less than R since the first deferral it is still `deferred` with no latch; at `>= R` it counts as `failed` and latches; a successful pin clears the held-since record | new |
| F1 | REQUIREMENT | `…::test_queued_sweep_after_clock_rollback_never_deletes_a_new_commit` | **Premise:** a publication is paused before commit with the store lock held; a sweep task is queued behind it; the injected clock is moved to `generation_expiry(GEN)` and then rolled back to `T0` before the publication is released. **Outcome:** the publication commits at `T0`; the queued sweep reports `deleted == 0`; the new artifact reads back exactly. `test_reap_refuses_a_now_ahead_of_the_store_clock` (Call 3) is **deleted**: the parameter no longer exists | ported from the reviewer's `queued-clock` probe |
| F2-1 | REQUIREMENT | `…::test_consistent_rewrite_is_refused_while_the_process_lives` | **Premise:** the payload, outline and manifest of an unexpired artifact are rewritten consistently by plain `Path` writes, and a payload-only rewrite is first refused with `payload_changed`. **Outcome:** the consistent rewrite is refused with `payload_changed` | ported from the reviewer's `mutable-manifest` probe |
| F2-2 | REQUIREMENT | `…::test_committed_at_tamper_is_refused_while_the_process_lives` | **Premise:** only `committed_at` is changed, to a later valid time in the same hour. **Outcome:** the read is refused at the original `committed_at + R` (or earlier, with `payload_changed`); it never succeeds at or after the original expiry | new |
| F2-3 | DOCUMENTED BEHAVIOUR | `…::test_after_restart_a_consistent_rewrite_is_the_documented_residual` | **Premise:** the store is stopped, and a **new** store instance is built on the same root; the artifact is then rewritten consistently. **Outcome**, quoted in the docstring: *"after a restart, a read can check only that the payload, outline and manifest agree with one another"*. The rewrite is served before `generation_expiry(GEN)` and refused with `result_expired` from `generation_expiry(GEN)` on, never later | new |
| F2-4 | REQUIREMENT | `…::test_registry_bucket_evicted_with_its_generation` | **Premise:** the registry holds the generation's bucket before the sweep (assert through its public accessor). **Outcome:** after the sweep that removes the generation, the bucket is gone | new |
| F3-1 | DOCUMENTED BEHAVIOUR | `…::test_identity_change_inside_expired_generation_is_documented_outside_behaviour` (real lstat-hook swap) plus `…_injected` (the opened child's `verify()` raises, and the anchor is intact) | **Premise:** the artifact directory's inode differs after the swap, and the original was moved outside the workspace root. **Outcome**, quoted in the docstring: *"An entry inside an expired generation whose identity changes while the reaper removes it is treated as content placed there by a process outside ProbOS."* First sweep: `skipped >= 1`, `failed == 0`, publication admitted, `moved/payload.jsonl` untouched. Second sweep: `deleted == 1`, and the moved original is still intact | ported from the reviewer's `child-identity` probe |
| F3-2 | REQUIREMENT | `…::test_ancestor_change_above_generation_during_removal_latches`, as an injected variant (both platforms: the anchor's `verify()` raises when the walker pins the artifact directory) plus a real variant (`skipif(sys.platform == "win32")`: the namespace is renamed while the walk is inside the generation; Windows anchor handles deny that rename) | **Premise:** the anchor chain really changed: the injected raise was reached, or the namespace inode differs. **Outcome:** `failed == 1`; publication latched; an unexpired generation in the moved namespace is intact | new |
| F3-3 | REQUIREMENT | `…::test_enoent_on_the_leaf_is_success_but_enoent_in_the_chain_is_an_integrity_failure`, with its "vanished" variant **retargeted** | **Premise:** `_chain_intact` returns False for the **namespace (anchor)** pin, not the artifact pin. **Outcome:** `failed == 1` and the store latches. A vanished artifact-level chain with an intact anchor is "gone", which counts as success | existing test, retargeted |
| F4 | DOCUMENTED BEHAVIOUR | `…::test_posix_relocation_during_removal_is_documented` (`skipif(sys.platform == "win32")`; its both-platform pair is F3-1's injected variant) | **Premise:** a wrapper around `os.unlink`, active for one call, renames the artifact directory outside the root between `_leaf` and the unlink; assert that the rename happened before the unlink. **Outcome**, quoted in the docstring: *"removal acts on directory objects that were verified to be inside the expired generation when they were opened, not on their current pathnames"*. That entry is gone from its new location; the sweep reports `skipped >= 1`, `failed == 0`; every other entry at the new location survives. It first runs on CI | new |
| R2-1 | REQUIREMENT | `test_ad1240_tool_result_delivery.py::test_promise_survives_authority_loss[structured × loss × parallel]`, where loss ∈ {callsign change, `read_file` registration replaced, resolver redirected} | **Premise:** the loss is applied after the worked call is emitted (assert the emitted arguments). **Outcome:** the replacement resolver's and tool's call counters are 0. The refused request gets no `AGENTIC_TOOL_CALL_STARTED` or `COMPLETED` event and no executor pre-hook, post-hook or terminal observer. `stopped_reason == "error"` and `error == "reference_unavailable"`. `tool_calls` keeps the issued request; `tool_results` holds genuine outcomes only, in request order | probe R2 `test_parent_r2_lost_owner_erases_source_promise` |
| | | plus `…::test_refusal_before_later_real_error_reaches_correlation` (real `WorkItemAgenticExecutor`) | **Premise:** a refusal at index 0 and a genuine tool error at index 1. **Outcome:** `correlate_tool_outcomes` receives an id-joined projection, and the genuine error is attributed to its own call | new |
| R2-2 | REQUIREMENT | `test_ad1240_workspace_results.py::test_resolve_file_returns_only_the_checked_value`, plus a physical swap (junction or symlink, mirror skips) | **Premise:** a patched `Path.resolve` returns an ordinary file on the candidate's first visit and the private artifact on any later visit. **Outcome:** the real GET never returns private bytes (it returns 400, or the ordinary content). `resolve_file` resolves the candidate at most once and returns exactly the value it checked | probe R2 `test_parent_r2_second_resolution_exposes_private_bytes` |
| **R2-3** | **DOCUMENTED BEHAVIOUR** | `test_ad1240_workspace_result_lifecycle.py::test_documented_outside_write_in_expired_generation_is_removed` | **Premise:** a real artifact, and the injected clock at `end(G) + R`. The test process itself, using plain `Path` writes and no ProbOS tool, replaces `payload.jsonl` with a sentinel and adds `user-note.txt`; assert the sentinel is present before the sweep. **Outcome**, recorded in the docstring as the documented outcome: *"Once a generation's retention has expired, the reaper removes the whole generation, including any file that a process outside ProbOS wrote or substituted inside it; the sweep counts the generation as deleted, reports failed=0, and does not latch publication."* Concretely: the generation directory is gone; `deleted == 1`, `failed == 0`, `deferred == 0`; a new publication is accepted | **replaces** probe R2 `test_parent_r2_actual_reaper_deletes_postvalidation_replacement`. Its reaping-marker hook and its `expires_at` clock premise no longer exist |
| R2-3a | REQUIREMENT | `…::test_unexpired_generation_never_reaped` | **Premise:** the current generation's payload is tampered. **Outcome:** sweeps at every clock `< end(G) + R` remove nothing; a read gives `payload_changed` and never the tampered bytes | new |
| R2-3b | REQUIREMENT | `…::test_link_in_expired_generation_is_not_followed` (Windows junction / POSIX symlink, mirror skips) plus `…_injected` (an entry reported as a reparse point) | **Premise:** a link inside an expired generation points at an outside directory that holds a sentinel. **Outcome:** the outside sentinel survives; the link is left in place; `skipped >= 1`, `failed == 0`; the generation directory is retained | new |
| R2-3c | REQUIREMENT (issue acceptance 5) | `…::test_logical_expiry_at_24h_physical_at_generation_end` | **Premise:** commit at `start(G) + 1800`. **Outcome:** the read succeeds at `committed_at + R − 0.001` and refuses with `result_expired` at `committed_at + R`. A sweep at that moment deletes nothing; a sweep at `end(G) + R` deletes the generation. The injected `sleep` is never called. No wall-clock sleep anywhere | new |
| R2-4 | REQUIREMENT | The five tests below, **unchanged** (their files are not edited) | They pass because the binder becomes a descriptor (§3.7) | — |
| R2-4.1 | REQUIREMENT | `tests/test_ad1209_work_item_status.py::test_the_tool_is_actually_offered_to_the_loop` | unchanged and passing | |
| R2-4.2 | REQUIREMENT | `tests/test_ad1226_recall_artifact.py::test_the_tool_is_not_offered_when_the_flag_is_off` | unchanged and passing | |
| R2-4.3 | REQUIREMENT | `tests/test_ad1226_recall_artifact.py::test_the_tool_is_actually_offered_when_the_flag_is_on` | unchanged and passing | |
| R2-4.4 | REQUIREMENT | `tests/test_bf731_captain_llm_lane.py::test_executor_forwards_priority_into_the_loop` | unchanged and passing | |
| R2-4.5 | REQUIREMENT | `tests/test_bf731_captain_llm_lane.py::test_executor_without_priority_omits_the_kwarg` | unchanged and passing | |
| R2-5 | REQUIREMENT | `test_ad1240_workspace_results.py::test_ordinary_inspection_resolve_budget` | **Premise:** 10 directories × 100 files, written with `write_bytes(b"ordinary fixture\n")`. **Outcome:** exactly 200 entries in deterministic order; `total_bytes == 17000`. `Path.resolve` calls, counted separately for each operation, are ≤ D + 1 + (directories descended) + (link entries), where `D = len(base.parents) + 1`. For this fixture (10 directories, no links) that is **≤ D + 12** for both `list_files` and `total_bytes`. An alias swap between calls gets a fresh decision. **No `git show` baseline**: assert the explicit expected outputs. (These bounds replace the Revision-0 bounds of D + 220 and D + 1040; round 1 measured 209 and 1019 under them.) | probe R2 `test_parent_r2_ordinary_inspection_cost_measured` |
| R2-5b | REQUIREMENT (M2 cost ruling) | `test_ad1240_workspace_results.py::test_resolve_count_independent_of_file_count` | **Premise:** two otherwise identical trees, one with a 5,000-file directory and one with a 5-file directory, and the same directory count. **Outcome:** each operation makes the same number of `Path.resolve` calls on both trees; outputs match the explicit expected names and sizes. The existing alias and case-variant tests pass unchanged | new |

**Requirements that exist because of this re-derivation:**

| ID | Requirement | Test |
|---|---|---|
| N1 | `AgenticLoop` keeps ≤ 13 direct methods | `tests/test_ad1324_srp_layout.py` passes **unchanged** |
| N2 | No new `srp-size` row; `architecture-baseline.yaml` is byte-identical | `scripts/check_architecture_principles.py --check` exits 0, and `test_ad1324_srp_layout.py::test_architecture_baseline_is_byte_identical_to_the_reviewed_base` passes |
| N3 | Rollover mid-publication never commits outside its generation | `test_ad1240_workspace_result_lifecycle.py::test_rollover_mid_publication_commits_in_next_generation` |
| N4 | A backward clock never puts a publication into an earlier generation and never shortens retention | `…::test_backward_clock_uses_high_water_generation` |
| N5 | Identity-cache entries under a removed generation are evicted | `…::test_reaped_generation_identities_are_evicted`. **Premise (F6):** before the sweep, assert `any(p.is_relative_to(namespace / GEN) for p in identities.known())`, using `DirectoryIdentities.known()` (a read-only diagnostic accessor). **Outcome:** after the sweep no such path remains |
| N6 | Strict profile behaviour is unchanged by AD-1240 | `test_ad1240_tool_result_delivery.py::test_strict_profile_keeps_legacy_delivery_and_trace_bytes` |
| N7 | Below-threshold behaviour is byte-identical to current `main` | `test_ad1240_tool_result_delivery.py::test_legacy_requests_match_pre_edit_golden` against the golden re-captured in M0 |
| N8 (D1) | Entries the pinned primitives refuse are left in place, `skipped`, and never latch | `test_ad1240_workspace_result_lifecycle.py::test_posix_only_entry_names_the_primitives_refuse_are_left_in_place` (`skipif(sys.platform == "win32")`; it first runs on CI). **Premise line:** `assert PureWindowsPath(str(odd)).is_reserved() or name in ("with:colon", "trailing.", "back\\slash")`. Also `test_entry_refused_by_the_pinned_primitives_is_foreign_unless_the_chain_failed`, whose "broken" variant includes a transient × broken-anchor case that expects `failed == 1` |

**Acceptance rows from the Call 6 rulings:**

| ID | Disposition | Acceptance test (file :: name) | Premise asserted first → required outcome |
|---|---|---|---|
| C6-D1-1 | REQUIREMENT | `test_ad1240_tool_result_delivery.py::test_owned_steps_page_above_threshold_stays_inline_and_is_acknowledged`, in both transcript modes, armed with a real store on `tmp_path`. It reuses the `tests/test_ad1192_owned_steps_dm.py` helpers by import; that file is not edited | **Premise:** `12288 < len(raw.output.encode("utf-8")) <= 16 * 1024` and `type(raw) is OwnedStepsViewResult`. **Outcome:** no file exists under `.tool-results`; the next request carries the exact page; `admit_owned_steps_presentation` is awaited exactly once |
| C6-D1-2 | REQUIREMENT | `…::test_ordinary_16k_result_with_the_owned_steps_metadata_key_still_offloads` | **Premise:** a different tool returns a plain `ToolResult` of 16 KiB that carries `metadata["owned_steps_view_reference"]`. **Outcome:** `result_delivery(...).status == "workspace"` |
| C6-D1-3 | REQUIREMENT | `…::test_plain_result_from_a_tool_named_read_owned_steps_is_not_exempt` | **Premise:** a fake registered as `read_owned_steps` returns a plain `ToolResult` of 16 KiB. **Outcome:** it is offloaded and never acknowledged |
| C6-D1-4 | REQUIREMENT | `tests/test_ad1192_owned_steps_dm.py`, all cases, **unchanged** | All pass (105 collected per the M4a report) against the final bytes |
| C6-D2 | REQUIREMENT | `test_ad1240_tool_result_delivery.py::test_delivery_remaining_follows_both_ad1208_ceilings`, parametrized. **Premise in each case:** tier-1 steps really inflated `iteration` (assert `result.iterations` against the counted steps) | (a) armed, `max_iter=3`, `max_total=8`, two tier-1 steps, then a large non-tier-1 result at `iteration=3`: offloaded, recovered, `complete` (the old formula gives 0 and refuses). (b) armed, the large result on the step that brings `counted` to `max_iter - 1`: refused with `recovery_iterations_unavailable`. (c) unarmed: unchanged, `max_iter - iteration`. (d) one AD-1324 redo call reduces the remainder by one |
| C6-D4.1 | REQUIREMENT | `test_ad1240_workspace_result_lifecycle.py::test_shutdown_stops_the_store_even_when_the_pool_step_raises` | **Premise:** `_stop_pools_and_drain_intent_bus` is patched to raise `RuntimeError`, and the test asserts it was called and raised. **Outcome:** the recording store's `stop` ran; the reaper task is done and the worker drained, both in normal shutdown and in rollback mode |
| C6-D4.2a | REQUIREMENT | `…::test_cancellation_during_store_start_never_starts_the_identity_registry` | **Premise:** the cancellation is delivered inside `store.start()`. **Outcome:** `AgentIdentityRegistry.start` is never awaited (it is patched to record calls), and the store was stopped |
| C6-D4.2b | REQUIREMENT | `…::test_identity_registry_start_failure_stops_the_started_store` | **Premise:** `AgentIdentityRegistry.start` raises after the store has started. **Outcome:** the store is stopped and the error propagates. M4b's existing failure-after-start tests stay |
| C6-D5 | REQUIREMENT (pre-authorised adaptation, R-a) | each test file the suite finds failing because production callers are armed-unavailable | **May be adapted only when all three hold:** (1) the failure is `workspace_unavailable` or `recovery_iterations_unavailable`; (2) it comes from a production caller (`WorkItemAgenticExecutor` or `NativeBuilderHarness`) on a fake runtime; (3) the test's subject is not result size, truncation or caps. **Adaptation:** shrink the incidental vector below 12,288 UTF-8 bytes, add the inline premise `assert len(x.encode("utf-8")) <= TOOL_RESULT_THRESHOLD_BYTES` and the comment `# AD-1240 (#1239): the vector's size was incidental; armed delivery is tested in test_ad1240_*`, and leave every other assertion unchanged. **Each such file joins the footprint** (§2 rows 30+) and is listed in the Builder report with its reason. Anything else is a hard stop (§6) |

---

## 2. Obtaining the candidate: action per path

Read each candidate path with `git show refs/preserved/ordinary-1239-e38710b8:<path>`. Read its base-to-candidate diff with `git diff 0ae79d95a1746d91e03f5ceb59b5b6d75600c735 refs/preserved/ordinary-1239-e38710b8 -- <path>`.

| # | Path | Action | Must survive from `main` / notes |
|---|---|---|---|
| 1 | `DECISIONS.md` | **drop** | trackers are edited at ship time, not by the Builder |
| 2 | `PROGRESS.md` | **drop** | same |
| 3 | `docs/development/open-ads-report.md` | **drop** | generated (`scripts/gen_ad_ledger.py`) |
| 4 | `docs/development/workspace-tool-results.md` | **adapt** (M5) | rewrite the "Workspace ownership" layout, "Lifecycle, retention and rollback" and "Contract tests" sections for generations, the taxonomy and the revised guarantee (§9); keep the rest |
| 5 | `src/probos/cognitive/agentic_dispatch.py` | **fresh edit** (M4) | Main moved the loop construction to `:3879–3890` and AD-1129's `_context.update` to `:3755`, before the loop. Preserve `on_model_request_presented` (`:3876`), the AD-1320..1325 keywords in `_loop_kwargs`, `MCP_DISPATCH_OFFER_CONTEXT_KEY` (`:3892`) and the manifest offer (`:3894`). Add the descriptor assignment and `workspace_delivery_context` after `:3890`, and the R2-1 `_ExecutedOutcomePairs` adapter at the `correlate_tool_outcomes` call (`:4111`) |
| 6 | `src/probos/cognitive/swe_harness/agentic_loop.py` | **fresh edit** (M4); the candidate's 18 hunks are a reference only | see §4.M4. Main rewrote `_execute_one_tool` (`:2362–2685`) and `_run_scoped` |
| 7 | `src/probos/cognitive/swe_harness/native_builder.py` | **adapt** (M4) | the binder call becomes an assignment (§3.7); construction is at `:137`, `loop.run` at `:157` |
| 8 | `src/probos/cognitive/swe_harness/result_offload.py` (new) | **adapt** (M4) | add the R2-1 lexical selection before the registry and `InvocationRefusal`; add `WorkspaceResultsSlot`; put the generation into the preview path |
| 9 | `src/probos/cognitive/swe_harness/tool_call.py` | **adapt** (M4) | Start from the candidate's version of the changed regions. Re-read main's 15-line drift since the base and keep it. The below-threshold renderer is untouched |
| 10 | `src/probos/cognitive/swe_harness/tools.py` | **fresh edit** (M4) | Main has +304 lines since the base, including AD-1316 `_locked_native_target`. Preserve every main-side strict and locking path. Adapt the private-slice path validation to the generation level |
| 11 | `src/probos/execution/workspace.py` | **adapt** (M2) | `WorkspaceManager` keeps reservation, `resolve_file`, `list_files`, `total_bytes`, `sanitize`, `key_for_agent`, `resolve` and `venv_dir`. **All result publishing, reading, lifecycle and reaping moves to row 12a** (N2) |
| 12 | `src/probos/execution/workspace_results.py` (new) | **adapt** (M1) | keep the protocol, records and capture. Add the generation constants and parser, the `WorkspaceReapResult.deferred` field and the path predicate |
| 12a | `src/probos/execution/workspace_result_store.py` (**new; not in the candidate**) | **write** (M1) | `WorkspaceResultStore` and `GenerationReaper` (§3) |
| 13 | `src/probos/runtime.py` | **fresh edit** (M4) | Main moved: `self.registry = AgentRegistry()` is at `:645`; `self.identity_registry = infra.identity_registry` is at `:2717`. Add `self.workspace_results` beside each |
| 14 | `src/probos/security/file_access.py` | The candidate's version, **plus one authorised deviation** (D2): a 5-line public wrapper `def is_reparse_point(info: os.stat_result) -> bool: return _is_reparse(info)` with a one-line docstring, placed immediately after `_is_reparse`. `main` is unchanged since the base | **Do not** add the R2-conditional `remove_file(expected=…)` or `remove_directory(expected_identity=…)` API, and make no other change |
| 15 | `src/probos/startup/infrastructure.py` | **fresh edit** (M4) | Main wraps Phase 1 in `try: … except BaseException:` with effect-broker and authority unwinding (`:58–139`). **Start the store after `await trust_network.start()` and before the `# --- Sovereign Agent Identity (AD-441) ---` block, so before the identity registry (C6-D4.2)**; this replaces Revision 0's "after `identity_registry.start()` (`:117`)". Return it in `InfrastructureResult` (`:121–127`). **Stop it in the `except BaseException` unwind.** Preserve the AD-1315/1316 construction at `:59–85`, and leave main's unwind otherwise byte-identical: do not add an identity-registry stop. A missing, `""`, `"."` or `Path()` root keeps the typed unavailable owner (C6-D4.3) |
| 16 | `src/probos/startup/results.py` | **fresh edit** (M4) | append `workspace_results: WorkspaceResults = field(default_factory=UnavailableWorkspaceResults)` after `effect_broker` (`:84`) |
| 17 | `src/probos/startup/shutdown.py` | **fresh edit** (M4) | Exclude the store's `background_tasks` from the AD-824 cancel sweep (`:1311–1320`), so the store drains its own worker. Inside the existing `with steps("pools stop and intent bus drain"):` (`:1899–1902`), wrap the helper call in `try:` and call `await workspace_results.stop()` in its `finally:`, keeping the deferred-cancellation `except asyncio.CancelledError` around that stop (C6-D4.1). `deferred_shutdown_cancellation` is initialised earlier in `shutdown()`. **Add no new guarded step; do not edit the BF-882 pins or `tests/test_issue1419_failed_start_rollback.py`** |
| 18 | `src/probos/tools/work_item_pull_tool.py` | **verbatim** (main is unchanged) | `WorkPullReceipt` subtype |
| 19 | `tests/fixtures/ad1240_below_threshold_golden.json` | **re-capture in M0** on unmodified `main` | its `"base"` becomes `1c9abde5bcde5fef96f2035ff319f81b0c002ff9` |
| 20 | `tests/test_ad1007_capability_gate.py` | **drop** (leave main's file untouched) | the descriptor makes binder stubs unnecessary |
| 21 | `tests/test_ad1142_crew_child_compaction.py` | **drop** | same |
| 22 | `tests/test_ad1155_loop_until_done.py` | **drop** | same |
| 23 | `tests/test_ad1180_agentic_disposition.py` | **drop** | same |
| 24 | `tests/test_ad1191_delegation_wire.py` | **verbatim**: apply candidate blob `c28c082f` exactly (C6-D3). `main`'s blob equals the candidate base (`1b1c2570`) | No path-shape adaptation is needed, because the amendment asserts `delivery.reference is None` in the unavailable case |
| 25 | `tests/test_ad1240_tool_result_delivery.py` (new) | **adapt** (M0 harness, M4 tests) | set `_BASE = "1c9abde5bcde5fef96f2035ff319f81b0c002ff9"` |
| 26 | `tests/test_ad1240_workspace_result_lifecycle.py` (new) | **adapt and rewrite** (M1) | see the per-test disposition in §4.M1 |
| 27 | `tests/test_ad1240_workspace_results.py` (new) | **adapt** (M1, M2) | the path shapes gain `<GEN>` |
| 28 | `src/probos/tools/work_item_steps_tool.py` (**added by C6-D1**) | **edit** (M4) | Add `class OwnedStepsViewResult(ToolResult)` with the docstring of §3.12, and return it from the success path at `:136` with the same arguments. `_error` keeps returning a plain `ToolResult` |
| 29 | `tests/test_ad1320_agentic_budget_awareness.py` (**added by C6-D3**) | **edit, last** (M5) | Move the `native_builder.py` blob pin at `:615` to the frozen file's LF blob, **after** the mutation campaign and after `native_builder.py` is frozen. Keep the pin and add the inline reason from §4.M5 |
| 30+ | each C6-D5 R-a test file | **minimal adaptation** (whenever the whole-suite run finds one) | Only under the §1 C6-D5 rule. The reason is recorded inline in the test and listed in the Builder report |

The footprint is **24 tracked paths plus the C6-D5 files**. That is rows 4–19 and 24–29 (23 paths, counting 12a; rows 1–3 and 20–23 are excluded), the M0 strict-baseline fixture `tests/fixtures/ad1240_strict_profile_baseline.json`, and each row-30+ file. `tests/test_ad1192_owned_steps_dm.py` and `tests/test_issue1419_failed_start_rollback.py` are **not** edited. **Any other tracked path is a hard stop** (§6).

Count correction (Call 7): Revision 0 called the footprint "23 paths (22 counting 12a)". Counted row by row, rows 4–19 plus 12a are 17 paths and rows 24–27 are 4, which makes 21, or 22 with the fixture. The paths themselves are unchanged; only the count was wrong.

---

## 3. Design (binding)

### 3.1 Layout and generation names

```
<root>/<owner-key>/.tool-results/<GEN>/<agent-digest>/<artifact-id>/{payload.jsonl,outline.json,manifest.json}
```

These go in `workspace_results.py`, as public module-level names:

```python
GENERATION_SECONDS = 3600
GENERATION_NAME_RE = re.compile(r"\d{8}T\d{2}Z")          # fullmatch only
def generation_name(t: float) -> str: ...                 # UTC hour of floor(t / 3600) * 3600, "%Y%m%dT%HZ"
def generation_start(name: str) -> float: ...             # strict parse; must round-trip; else WorkspaceResultError("generation_invalid")
def generation_expiry(name: str) -> float:
    return generation_start(name) + GENERATION_SECONDS + RESULT_RETENTION_SECONDS
```

The name is 12 characters and fixed width. `RESULT_RETENTION_SECONDS` stays `86400`. A clock value must be finite: reuse the candidate's `_result_time`, now public as `result_time` in `workspace_results.py`.

### 3.2 Publication (`WorkspaceResultStore`)

- `high_water: float` is process-local, starts at `-inf`, and is **never restored from disk**.
- **Generation.** At admission, under `_result_lock`: `G = generation_name(max(clock(), high_water))`.
- **Creation.** Pin `…/.tool-results/<G>/<digest>` with `create=True`. Create `<artifact-id>`, which is `secrets.token_hex(16)`, with `make_directory`. Write `payload.jsonl`, `outline.json` and `manifest.staged` with `write_new`, which uses `O_CREAT | O_EXCL`.
- **Commit time.** At commit, compute `committed_at = max(clock(), generation_start(G), high_water)`.
  - **If `committed_at >= generation_start(G) + GENERATION_SECONDS`:** do not publish this artifact. Leave it unadvertised, with no `manifest.json`; the reaper removes it with G. Retry exactly once in `generation_name(committed_at)`. A second rollover raises `workspace_write_failed`.
  - **Otherwise:** `publish_file("manifest.staged", "manifest.json")` (the hard link fails if the target exists), then set `high_water = committed_at` and record the artifact in `CommittedArtifacts` (§3.10).
  - **If `publish_file` raises (D3):** the artifact counts as committed only if `manifest.json` holds exactly the staged bytes. In that case, retry removing `manifest.staged` under the retry policy, and leave it in place if that still fails. In every other case, re-raise, which becomes `workspace_write_failed`. A manifest that differs from the staged one is never advertised.
- **Invariant:** every committed artifact in G has `generation_start(G) <= committed_at < generation_start(G) + 3600`.
- **Forbidden names** in `workspace_result_store.py`: `os.replace`, `os.rename`, `Path.replace`, `Path.rename`, `shutil.rmtree`, `shutil.move`. The test `test_store_source_never_overwrites_by_rename` parses the module AST and fails on any of these names, as `ast.Attribute` or `ast.Name`.
- **Removing `manifest.staged`** after a successful link uses the retry policy (§3.5). If it still fails, leave it: the artifact is committed, and the staged file goes with its generation.
- The candidate's `publication.json` marker is **not built**.

### 3.3 Reading

`read_tool_result_slice` validates the path shape `…/.tool-results/<GEN>/<digest>/<artifact-id>/payload.jsonl`, with `GENERATION_NAME_RE` and the candidate's hex checks. Then, in order:

1. **Before any I/O:** if `clock() >= generation_expiry(GEN)`, raise `result_expired`.
2. Run the existing manifest checks: build the reference from `manifest.json` and `outline.json`.
3. **Registry check (F2, §3.10), immediately after the reference is built:**
   ```python
   recorded = self._committed.get(path)
   if recorded is not None and recorded != _Committed.of(reference, owner_digest):
       raise WorkspaceResultError("payload_changed")
   ```
   Keep the `if recorded is not None and recorded != …` line as a single physical line; it is mutation row 18's anchor.
4. Require `generation_start(GEN) <= committed_at < generation_start(GEN) + 3600`. Otherwise raise `manifest_invalid`.
5. Run the existing `clock() >= committed_at + R` check (`result_expired`), then the digest check, which raises `payload_changed`. Within the process lifetime both now run on values the registry has confirmed.
6. Opening `payload.jsonl` uses the retry policy, for winerror 32 and 33 only.

**Every artifact read goes through `WorkspaceResultStore.read_tool_result_slice`.** No other module may read files under `.tool-results`, or it bypasses the registry.

### 3.4 Reaping (`GenerationReaper`)

**Generation selection.** The reaper decides from the name and the clock only, and never reads a manifest:

```python
if GENERATION_NAME_RE.fullmatch(name) is None: skipped += 1; continue
if now >= generation_expiry(name):            # remove the whole generation
```

**What gets skipped and preserved:**
- non-generation names;
- names that do not round-trip;
- future names;
- unexpired generations, which are left untouched and not counted.

**Removal of one expired generation.** Use a bounded, bottom-up walk built only from `pin_directory`, `list_names`, `remove_file` and `remove_directory`, to **depth 3** below `<GEN>`, with a per-sweep cap of 10,000 entries:
- Remove every regular file and every real directory, **whatever its name**, that the pinned primitives accept.
- **Never descend into, follow or remove** a symlink, junction, reparse point or special file. Check with `lstat` and `is_reparse_point` (D2). Leave it in place and count `skipped`; its generation directory is retained.
- An entry the primitives refuse by name (`_leaf` rejects `:`, `\`, a trailing dot or space, and reserved device names) is left in place and counted `skipped` (D1).
- An entry beyond depth 3 is left in place and counted `skipped`.
- Entries beyond the cap are `deferred` to the next sweep. A cap deferral never escalates (Call 3 repair 2).

**Counts.** `deleted` counts whole generations removed.

**Settling a failure against the anchor chain (F3).** The **anchor** is the namespace pin (`owner`, the pinned `<root>/<owner-key>/.tool-results`) taken in `_reap_owner`. Thread it through `_reap_entry`, `_reap_directory` and `_settle`; `_reap_expired` passes `owner` as both `parent` and `anchor`. Every failure from `pin_directory(child, …)`, `child.list_names()`, the context exit's `verify()`, `parent.path`, `remove_file` or `remove_directory` is settled like this:

```python
def _settle(self, anchor, exc, tally) -> bool:
    if not _chain_intact(anchor):            # root -> owner -> .tool-results changed
        failed (+ error log); return False   # integrity: latches
    kind = classify_os_error(exc, platform=sys.platform)
    if kind == "gone":       return True     # the entry or subtree is already gone
    if kind == "transient":  deferred += 1; transient += 1; return False
    if isinstance(exc, (FileAccessDenied, ValueError)):
        skipped += 1; return False           # refused name or kind, or an identity change at or below <GEN>: foreign
    failed (+ error log); return False       # EACCES/EPERM/EROFS/EIO/ELOOP/ENOTDIR and unexpected types: integrity
```

- Keep `if not _chain_intact(anchor):` as a single physical line; it is mutation row 19's anchor.
- `_chain_intact(parent)` is no longer called anywhere.

**POSIX object confinement (F4).** On POSIX, `unlink` and `rmdir` act through directory descriptors. Removal is therefore confined to directory **objects** that were verified to be inside the expired generation when they were opened, not to their current pathnames. `_leaf` re-verifies the chain before each operation, which narrows the window but does not close it. This is documented (§9), not mitigated further.

**Eviction timing (D4, replaced by C9 A1-2).** When the removal of an expired generation **starts**, evict every `DirectoryIdentities` entry under it (N5). Its `CommittedArtifacts` bucket is evicted only when the generation's removal succeeds, or the generation is found already gone; a deferred, capped or held generation keeps its bucket, so a rewrite of its files is still refused if the clock moves back (§3.10). In `_reap_expired`, `evict_under` stays at the start and `self._committed.evict_generation(namespace, name)` sits in the `if self._reap_entry(...)` success branch, before `tally.deleted += 1`. Identities of the root, owner and namespace, and of unexpired generations, are untouched, so the R1-5(a) integrity detection still works. Residual: if a process outside ProbOS deletes a still-unexpired generation, the **two** kinds of identity cached for it (the generation directory and each agent directory beneath it) are never evicted, because the name is no longer listed, and publication into that generation fails with `workspace_write_failed` for the rest of its hour; it does not latch.

**Selection lives in a module function (C9 A1-5).** `_reap_generation` became the module-level `_is_expired(name, now, tally) -> bool`, not a reaper method, so `GenerationReaper` stays at 15 methods (the checker flags above 15). The row 1 and row 3 lines are unchanged in text, indented four spaces instead of eight.

**Remembered anchors (C9 A1-3).** "Remembered" means the anchor's exact path has an entry in this process's `DirectoryIdentities` (`knows(path)`); publication's chain pin and the sweep's successful root and namespace pins and listings remember it, and `evict_under` never evicts them. In `_reap_root`'s `FileNotFoundError` branch, `if existing == self._root and self._identities.knows(self._root):` counts an integrity failure and returns; in `_reap_namespace`, `if self._identities.knows(namespace):` re-raises, which `_reap_owner` counts as `failed`. A root or namespace never created, or not remembered after a restart, stays a healthy empty sweep. A failure to list the root itself (its second pin, after the probe) that is not transient does not return a failed tally: it raises `workspace_reap_failed` out of the sweep, which latches all the same, as it did before this change; a transient one is retried and, if it persists, returns a `deferred` tally and, held for one retention period, a `failed` tally, which latches (review round 5, finding 1). Builder A1 found the premise narrower than ruled: `PinnedDirectory.open` already raises `FileAccessDenied("previously pinned directory disappeared")` for a remembered path, so a real removal already latched; the `knows` branches fire when a pin reports a plain `FileNotFoundError` for a known path. The behaviour change in a live process is that the sweep's listing now remembers the namespace after a restart.

**Rotating cursor (C9 A1-4).** `self._capped_at: dict[Path, str]`, keyed by the root and each namespace. The root's owners and a namespace's names are visited in `_rotated(names, self._capped_at.get(directory))` order: sorted names after the cursor, then those up to it, or plain sorted order with no cursor. `_note_cap` records a name when the cap was reached inside it; a directory's cursor is dropped when its pass completes below the shared cap, and a pass that was deferred (a transient failure) or ended early keeps its cursor, which changes only the visiting order (review round 4, finding 3: the earlier wording said the cursor is dropped whenever a sweep ends under the cap). Only the visiting order changes, never which generations are selected. Within one generation the walk stays in name order (residual, §9). The owner loop runs with no root pin held: each namespace pin re-pins and re-verifies the whole chain.

**Restart.** No journal is kept. A partly removed expired generation is still expired, so the next sweep finishes it.

### 3.5 Failure taxonomy and retry

| Class | Windows | POSIX | Count, and whether it latches |
|---|---|---|---|
| Already gone | `FileNotFoundError` on the leaf | same | success |
| Transient | `PermissionError` or `OSError` with `winerror` in `{32, 33, 5, 145, 303}` | `errno` in `{EBUSY, EAGAIN, ETXTBSY, ENOTEMPTY}`; on `ENOTEMPTY`, re-list and remove again | retried; if the budget runs out, `deferred`; **no latch** |
| Integrity | any failure while the **anchor chain** (root → owner → `.tool-results`) does not verify (identity changed, reparse point in the chain, a previously pinned directory disappeared, an opened directory moved); missing fixed-point anchor; `clock_invalid`; inside an expired generation with the anchor intact, any `OSError` that is neither gone nor transient, and any exception type that is not `FileAccessDenied` or `ValueError` | the same, plus `errno` in `{EACCES, EPERM, EROFS, EIO, ELOOP, ENOTDIR}` | `failed`; **latches** |
| Escalated deferral | a generation that is still not removed, because of a **transient** failure, when `now >= generation_expiry(G) + RESULT_RETENTION_SECONDS`; or a root or namespace pin or listing that has been continuously deferred for `>= RESULT_RETENTION_SECONDS` (F5) | same | `failed`; **latches** |
| Foreign | non-generation or future names; links, special files and names the primitives refuse inside an expired generation; depth > 3; a `FileAccessDenied` or `ValueError` at or below `<GEN>` while the anchor is intact (F3) | same | `skipped`; never escalates |
| Capped | entries beyond `SWEEP_ENTRY_CAP` in one sweep | same | `deferred`; never escalates |

Classify with a pure function `classify_os_error(exc: BaseException, *, platform: str) -> Literal["gone", "transient", "integrity"]`. It takes `platform` explicitly, so both tables are tested on both CI platforms (`test_classify_os_error_table[platform × code]`).

**Retry policy.** It is a frozen dataclass `RetryPolicy(attempts=4, delays=(0.05, 0.2, 0.5), sweep_sleep_budget=2.0)`, injected together with `sleep: Callable[[float], None] = time.sleep`. Both are keyword arguments of the store and reaper constructors. Sleeping happens in the drained worker thread. The runner never sleeps past the per-sweep budget: if the next delay would exceed it, the failure is raised instead (D5). Tests pass a recording `sleep` and assert totals. **No test sleeps on the wall clock.**

**Root and namespace operations use the runner too (F5, retry scope replaced by C9 A1-5).** The climb probe, the root pin with its listing, and the namespace pin with its listing each run as one unit (pin, use, verify on close) under the sweep's `RetryRunner`, with a fresh pin for every attempt and `_transient` as the retry test. The namespace pin that generation removal runs under is entered under the runner; its closing check is not retried, because the removal work is never repeated, and a transient failure there defers the namespace. An exhausted transient there adds 1 to `deferred` (not to `transient`) and logs at WARNING. Integrity failures there still count as `failed`. The units are `_probe(path)` and `_listed(path)`, each one attempt that the caller retries whole through `runner.run(partial(...), _transient)`.

**Remembered anchor missing (C9 A1-3)** is an integrity failure: `failed`, latches (§3.4).

### 3.6 Latch and recovery

All the latch rules, in one place:

1. **What latches.** Any `failed > 0`, or a sweep that raises or is cancelled (for example `clock_invalid`, or `workspace_reap_failed` for a missing filesystem anchor), latches publication unavailable before sweep serialization is released. So do the reaper task ending with an exception or being cancelled, and a `start()` that fails or is cancelled (corrected in Call 10: the earlier list named only the first two). `deferred` and `skipped` never latch.
2. **What counts as failed.** Integrity failures, and the two escalations in §3.5.
3. **Recovery.** A completed `stop()` followed by a successful `start()`, whose sweep must report `failed == 0` (`deferred` and `skipped` are allowed). A clean public sweep never clears the latch. Starting while faulted but not stopped is refused. Unexpired typed reads stay available while the latch is set.
4. **The sweep's time.** `reap_tool_results()` takes **no argument** (F1). The sweep reads `result_time(self._clock())` inside the store lock, so a queued sweep can never use a time taken before a publication it waited for. It takes one sample per sweep and decides every removal in that sweep from it; a clock that steps backwards while a sweep is already removing does not stop that sweep (C9 A1-1, residual in §9). Remove the parameter from the protocol (`workspace_results.py`), from `UnavailableWorkspaceResults`, and from the store. No caller passes one: not tests, not startup, not the reaper loop, not shutdown.
5. **Generation escalation** (the 2R rule) is adopted and reversible. Its condition is `if tally.transient > transient_before:`, so cap deferral and foreign entries never escalate. Changing it to "warn only" means replacing the escalated-deferral branch with a `logger.error`. The residual is stated in the code comment: *a lock held for more than a further 24 h turns offload off until restart; with warn-only instead, such a lock would grow disk use without bound.*
6. **Root and namespace escalation (F5)** is adopted and reversible the same way.
   - The reaper keeps `self._held_since: dict[Path, float]`, in-process only.
   - On a deferred root or namespace pin or listing: `setdefault(path, now)`. On success: `pop(path, None)`.
   - When `now - self._held_since[path] >= RESULT_RETENTION_SECONDS`, count it as `failed`. Keep that line as a single physical line; it is mutation row 20's anchor.
   - Residual: without this rule, retention could stop forever while only log lines record it.
7. **Log wording (F7).** The sweep's deferral log line states availability from `self._faulted` after the failure handling. It says "publication stays enabled" only when the store is not faulted.

### 3.7 The binder (N1)

In `result_offload.py`, define `class WorkspaceResultsSlot` as a data descriptor:
- `__set_name__` records the private storage name;
- `__get__` returns the bound owner, or `None`;
- `__set__` rejects an owner that is not `WorkspaceResults`-valid (reuse the candidate's `is_workspace_results`), and rejects any assignment once the instance's first `run()` has started, raising `WorkspaceResultError`.

In the `AgenticLoop` class body, add one line: `workspace_results = WorkspaceResultsSlot()`. Then:
- `__init__` assigns its existing `workspace_results=` keyword through the slot;
- **add no method** to `AgenticLoop`;
- production callers assign `loop.workspace_results = resolve_workspace_results(runtime)` immediately after construction.

**Do not rename the slot and do not add a fallback for test doubles.**

### 3.8 Strict profile (N6), considered and deferred

When `getattr(self._executor, "protected_effects_enabled", False)` is true, which is the expression main already uses at `agentic_loop.py:2399`:
- the loop uses legacy delivery: no capture, no offload, no source promises;
- it logs once per run at INFO, without content;
- strict trace and event bytes must equal current main's. The test compares against a small committed fixture captured in M0 with the strict executor double from `tests/test_ad1316_governed_effect_broker.py` (reuse its existing helpers and add no new production surface).

**Plan mode (C8-F1):** legacy delivery when the AD-1156 allowlist excludes `read_file` (it does: `PLAN_MODE_TOOL_IDS` has no `read_file`). The loop is left unarmed, with one INFO log (§3.13).

### 3.9 R2-1 invocation refusal

Implement exactly the R2 conditional contract, restated here. Its source is `ordinary-1239-r2-architect-conditional.md` §2, a prior-session artifact outside this worktree; you do not need to read it.
- `invocation_context` selects the absolute lexical promise **before** any registry lookup, permission check, bind or resolver call.
- Once `RecoverRead` is selected, any later setup failure raises a content-free `WorkspaceResultError` and never becomes `None` or `FreshRead`.
- Record the reader identity at worked-call admission; a replacement reader is a refusal.
- Use `@dataclass(frozen=True) class InvocationRefusal: request_id: str; code: str`.
- `_execute_one_tool` and `_execute_tool_uses` may return `ToolCallResult | InvocationRefusal`. Resolve the refusal **before** `AGENTIC_TOOL_CALL_STARTED` fires (`agentic_loop.py:2401`). The refused request gets no executor call and no observers. The terminal outcome is `stopped_reason="error"` with `safe_delivery_error(code, …)`.
- Keep refusals positionally aligned in lists. Filter them only where outcomes are consumed, including the `zip(..., strict=True)` presentation sites at `agentic_loop.py:2040–2041` and `:2079`.
- In `agentic_dispatch.py`, pass an id-joined `_ExecutedOutcomePairs(tool_calls, tool_results)` to `correlate_tool_outcomes` (`:4111`). **`reply_value.py` is not changed.**
- **R2-1 covers workspace promises too (C8-F2):** an artifact path this run published is selected first, like a source promise, and a replaced reader is refused before invocation (§3.13).

### 3.9a Remaining iterations for delivery (C6-D2)

When AD-1208 is armed, the loop has two ceilings: the total, `iteration_ceiling` (`agentic_loop.py:1712–1718`, reduced by AD-1324 redo calls), and the counted one (`counted_iterations >= self._max_iter`, `:2322–2325`). Native reads are not tier 1, so the recovery step itself counts. In `_run_scoped`, immediately before each `_execute_tool_uses(...)` call:

```python
delivery_remaining = iteration_ceiling - iteration - redo_calls
if self._max_total_iter is not None:
    delivery_remaining = min(
        delivery_remaining,
        self._max_iter - counted_iterations - (1 if _counts_toward_max_iterations(tool_uses) else 0),
    )
```

- Pass it as keyword `delivery_remaining` through `_execute_tool_uses` to `_execute_one_tool` (all three call sites).
- Use `DeliveryContext(delivery_run, delivery_remaining)` at the `prepare_result` call.
- `DeliverySettings.max_iterations` stays, but delivery no longer reads it.
- Add no method.

### 3.10 The in-process committed-artifact registry (F2)

**What it is.** A new small class, `CommittedArtifacts`, in `workspace_result_store.py`. It is shared by `ArtifactIO` and `GenerationReaper` in the same way `DirectoryIdentities` is. It has four methods: `record`, `get`, `evict_generation` and `__len__` (or a read-only diagnostic accessor for tests).
- **Storage:** `dict[tuple[Path, str], dict[str, _Committed]]`, keyed by `(namespace, GEN)` and then by `os.path.normcase(str(payload_path))`.
- **Record:** `_Committed(sha256, committed_at, source_chars, utf8_bytes, outline_sha256, owner_digest, representation)`, a frozen dataclass with **seven** fields, built by the classmethod `_Committed.of(reference, owner_digest)`. `representation` was added in M1 round 2: without it, flipping only the manifest's `representation` went undetected.

**When it is updated:**
- **Record:** in `_publish_in`, immediately after the commit succeeds, beside `self._high_water = committed_at`.
- **Check:** in `read`, immediately after `_result_reference` and before the commit-hour range check (§3.3 step 3).
- **Evict (C9 A1-2):** drop the whole `(namespace, GEN)` bucket in `_reap_expired` only on the path where the generation's removal succeeded or the generation was already gone. Never earlier: an earlier eviction would let a changed `committed_at` or a consistent rewrite be served again if the clock moves back. A generation that is never removed keeps its bucket until restart.

**Memory bound.** One entry for each artifact committed in roughly the last 25 hours, plus any generations still held (at most one hour of commits per held generation); about 0.75 KB each (744 bytes per entry measured by recursive `sys.getsizeof` over 1,000 entries, excluding allocator overhead). The registry is not durable, so it does not conflict with "no durable source registry", which forbade restart-validated source promises.

**What it buys (C9 A1-6; qualified after review round 4).** While this process holds an artifact's commitment record (from its commit until its generation is removed whole or found already gone, or the process ends), a read refuses an artifact whose files differ from what this process committed in any recorded value: the payload's SHA-256, character count and UTF-8 byte count, the outline's SHA-256, `committed_at`, `representation` and the owner digest. That includes a consistent rewrite. Manifest keys the record does not hold (an added key, a reordering) are not compared and do not cause a refusal.

**What it does not buy.** After a restart the registry is empty. A read then checks only that the payload, outline and manifest agree with one another. A consistent rewrite by a writer with ProbOS's own OS identity is served, but never past `generation_expiry(GEN)`, which is decided from the directory name. Do **not** refuse every unregistered artifact after a restart: that would make ProbOS-produced data unreadable before its retention expires. After a restart the outline is checked only to be ASCII and to match the manifest's `outline_sha256`; it is not parsed, so an outline that is not JSON is returned as stored. The same restart-grade check applies in the running process once a generation has been removed whole: its record is dropped then, so if the clock steps back far enough for the generation's name to read as unexpired again, an artifact that a process outside ProbOS places at the same location is read like any other. A generation directory that a process outside ProbOS removes before its expiry is never listed again, so its record stays in memory until the process ends (about 0.75 KB per artifact).

**Budget.** `ArtifactIO` gains about 8 lines and no method.

### 3.11 The ordinary workspace walk (M2 cost ruling)

`list_files` and `total_bytes`:

1. Resolve the base once.
2. Walk with `os.scandir`. Take each entry's `DirEntry.stat(follow_symlinks=False)` (free on Windows), and check it with `is_reparse_point`, `is_symlink()` and `is_junction()`.
3. **Plain regular file** (not a reparse point): no `resolve`. Emit its name and its size from that `lstat`.
4. **Real directory:** prune it if `entry.name.casefold() == RESULT_DIRECTORY`; keep that test as a single physical line, because it is mutation row 23's anchor (it sits in `_children` and drops any entry of that name, whatever its kind). Otherwise resolve the directory **once**, check that the resolved path is under the base and is not private, and descend.
5. **No-follow descent (A2 repair).** `_listing` observes the directory with `os.lstat` (no-follow) before the scan and again after it (`_is_checked_directory`), and uses the listing only if both observations show a real directory (`S_ISDIR`), not a reparse point, with the identity taken from its scan entry. A link, junction or other reparse point is refused even when it leads to the very object that was checked. The `os.lstat` line is mutation row 33's anchor.
5a. **One classification per observation (review round 4).** `_children` classifies a scan entry through the module-level `_classify(entry, info) -> (is_dir, link)`: the link flag, and the kind of anything that is not a link, come from the observation `info`; for a link, the kind of its target is the scan entry's own answer (`entry.is_dir()`), which may have been cached when the directory was scanned (review round 5, finding 2). A real directory is observed a second time (`os.lstat(entry.path)`, because a scan entry's stat carries no identity on Windows) and classified again from that observation, so a `_Child` never combines a fresh stat with a stale link flag or, for a non-link, a stale kind: a directory that became a link in between is a link (listed once, never sized or entered), and one that became a file is a plain file. The second `_classify` line is mutation row 44's anchor.
6. **Link, junction or other reparse point:** resolve it once, and prune it if it points into the namespace or outside the base. This keeps the R1-2 alias pruning. A kept link to a directory is listed once, with size 0, and is never entered or sized (its target is walked once, as itself); the opaque test `child.is_dir and not child.link and child.name in _OPAQUE_DIRS` is mutation row 34's anchor. A kept link to a file is sized from its checked target.
7. Memoize only within one walk. Preserve ordering, limits, sizes and the opaque-directory behaviour.

**Residual (A2).** Only the directory's own final component is observed. An ancestor swapped for a same-object alias between a scan and a child's descent could still expose that child's plain-file names and sizes (§9).

**R2-2 is unaffected:** `resolve_file` still resolves once and returns only the checked value.

**Hard-link residual.** A hard link created by a process outside ProbOS is indistinguishable from an ordinary file, and is listed and served as one. Do **not** refuse `st_nlink > 1`: uv-style hard-linked virtual environments would break.

### 3.12 Producer-owned inline results: the owned-steps exemption (C6-D1)

AD-1192 gives authority to the **exact** page text the model saw: `_acknowledge_owned_presentation` (`agentic_dispatch.py` around `:3903–3926`) requires `presentation.output == rendered`. An offloaded page is never added to `PresentedToolResult` (§4.M4), so it could never be acknowledged. The producer caps a page at `MAX_OWNED_VIEW_BYTES = 16 * 1024` (`work_item_steps.py:29`), so keeping it inline stays bounded, exactly as on `main`.

**Identification is by producer-owned type, never by tool id or metadata.** Any tool can attach a metadata key; that is the AD-1187 rule: "dictionary flags or text resemblance confer no exemption".

1. `src/probos/tools/work_item_steps_tool.py` (§2 row 28), after the imports:
   ```python
   class OwnedStepsViewResult(ToolResult):
       """Producer-admitted complete owned-steps page; its exact text authorises acknowledgement, so it is never offloaded."""
   ```
   The success path at `:136` returns `OwnedStepsViewResult(output=rendered, duration_ms=..., metadata={...})`, with the same arguments as today. `_error` keeps returning a plain `ToolResult`.
2. `result_offload.py` `_prepare_result`, immediately after the `WorkPullReceipt` branch (`:515`). The condition is one physical line, because it is mutation row 24's anchor:
   ```python
   if type(raw) is OwnedStepsViewResult and raw.error is None:
       _admit(text, settings.max_chars)
       return captured.legacy_result()
   ```
   Import it from `probos.tools.work_item_steps_tool`. That module imports only `probos.work_item_steps` and `tools.protocol`, so there is no import cycle.
3. **No change** to `agentic_loop.py` or to dispatch for this exemption. An exempted result has no delivery, so it is presented and acknowledged as on `main`. `_record_tool_result` (`agentic_dispatch.py:2829–2849`) keys on the tool id and metadata, and a subclass preserves both. The only exact-`ToolResult` check in production (`agentic_dispatch.py:510`) concerns `run_python`.

**There are exactly two producer exemptions:** `WorkPullReceipt` and `OwnedStepsViewResult`. Adding a third is a hard stop (§6).

**Enumeration of complete or large producers** (Call 6, working tree). Searches run: `Grep render_complete|ToolResultPresentation|_tool_result_presentation src/` and `Grep "class \w+\((ToolResult|SourceToolResult)\)" src/`.

| Producer | Can it exceed 12,288 bytes? | Does a consumer depend on the exact inline text? | Disposition |
|---|---|---|---|
| Work pull (AD-1187) | yes | yes (receipt) | already exempt (`WorkPullReceipt`) |
| Owned steps (AD-1192) | yes, up to 16 KiB | **yes** (acknowledgement) | exempt (`OwnedStepsViewResult`) |
| `review_requests` list (AD-1213) | yes, when `max_chars = 0` | no | offload is correct; the content stays recoverable |
| `self_query` | only if 6,000 retained characters are mostly multi-byte | no | offload is correct; its validation is kept |
| `DelegatedToolResult` (AD-1191) | yes | its evidence stays inline | already handled |
| `FindingToolResult` | — | no: the evidence comes from `result.publication`, which an observer reads before conversion | offload is correct |
| AD-1200 instruction and source results | — | M3's source and recovery types handle them | handled |

**Page size (Call 10 correction).** `MAX_OWNED_VIEW_BYTES` bounds the view JSON, not the rendered text, so a rendered owned-steps page can reach about 16.8 KB (orchestrator measurement, not re-measured in Call 10). It is still admitted against the message cap, and `delivery_frame_too_large` stops the run if it does not fit.

### 3.13 Delivery: the promised reader and workspace promises (C8-F1, C8-F2)

**The recovery reader is offered full when delivery is armed (C8-F1).** The AD-1189 manifest freezes its withheld set at the first `present()`, so a deferred `read_file` would be refused when the model followed a worked call. In `agentic_dispatch.py`, before `def _build_tools`, two single-line predicates:

```python
_delivery_armed = plan_mode_tool_ids is None or "read_file" in plan_mode_tool_ids
_recovery_reader_full = _delivery_armed and not executor.protected_effects_enabled and not isinstance(resolve_workspace_results(runtime), UnavailableWorkspaceResults)
```

- `_build_tools`' `keep_full` condition gains `or (tid == "read_file" and _recovery_reader_full)`. `_refresh_tools` rebuilds through the same `_build_tools`, so the clause holds after every refresh, including with the AD-1241 MCP offer.
- The strict profile and an unavailable owner keep AD-1189's withholding unchanged; the strict bytes stay equal to main.
- **Plan mode keeps legacy delivery.** `loop.workspace_results = …` and the delivery-context update run only `if _delivery_armed:`; otherwise one INFO line: `"AD-1240: plan mode offers no recovery reader; this run keeps legacy delivery"`. A plan-mode read allowance limited to promised paths would relax the AD-1156 allowlist and is not chosen (it would be the Captain's call).
- Residual (Low, documented, not fixed): a failed recovery read through a reader that is not in the dispatch offer is labelled unknown in AD-1248 failure summaries, because `offered_names` comes from dispatch's build only.

**Run-local workspace promises (C8-F2).** `SourceRecoveryScope` gains `_workspace: set[str]` and two methods (6 → 8 methods counting `__init__` and `_key`):
- `reserve_workspace(reference)` requires `type(reference) is WorkspaceResultRef` and an active scope, then adds `self._key(reference.path)`;
- `workspace_promised(path) -> bool` is false for a closed scope or a non-absolute path, otherwise membership; `close()` clears the set.

In `result_offload.py`:
- the workspace branch calls `context.run.scope.reserve_workspace(reference)` immediately after the frame is admitted, so a promise exists only for an admitted frame;
- `invocation_context` checks `if Path(path).is_absolute() and self.scope.workspace_promised(path):` before `self.scope.select(path)` and returns `await self._promised_context(tool_id, path, None)`;
- **alias spelling (Builder B deviation, accepted):** inside the `try`, after the reader resolves the target, `promised_workspace = self.scope.workspace_promised(str(target))` is recorded and `bind()` is skipped for it; the decision `if promised_workspace: return await self._promised_context(tool_id, str(target), None)` is made **after** the `try`, because a refusal raised inside it would be swallowed into `return None` (a fresh read);
- `_promised_context` is `async` and accepts `directive: RecoverRead | None`. With `None` it requires `tool_id == "read_file"`, binds, takes `self.reader()`, checks `admitted_reader.matches(reader)` (the reader identity fixed at first admission) and `_registration`, resolves the target through that reader, and refuses on `if target != Path(os.path.normpath(path)): raise WorkspaceResultError("source_changed")` (review round 4: the target is compared with the lexically normalized spelling that `workspace_promised` selected the promise by, so an equivalent absolute spelling of the published path, one containing `..` for example, recovers through the unchanged reader, while the original `path` is still what `resolve_source_path` receives); it returns a `WorkspaceReadContext` with `FreshRead(self.agent_id, self.scope.run_nonce)`. Any failure becomes `reference_unavailable` through the existing wrapper, before the call starts. `DeliveryRun` gains no method.

An artifact path never promised still takes the typed fresh route with owner, digest and expiry checks. Repeated slices of a promised path validate each time. A new top-level run has a new scope. The strict profile and plan mode open no delivery run and hold no promises. Every recovery worked call is `read_file`, so `codebase_read_source` recoveries are covered by the same checks.

---

## 4. Milestones

Each milestone is one synchronous Builder run of about 90 minutes or less. It ends at a green focused checkpoint the orchestrator can rerun. Commit nothing; the orchestrator stages. At each exit, report the files touched, the collected and passed counts, and the import-root line.

### M0. Re-capture the golden on unmodified `main`, and record the strict baseline

- **Files:** `tests/test_ad1240_tool_result_delivery.py`, harness only; `tests/fixtures/ad1240_below_threshold_golden.json`; `tests/fixtures/ad1240_strict_profile_baseline.json` (new; it counts within row 25's milestone and is the only fixture addition allowed).
- **Do:**
  1. Before **any** `src/` edit, copy the candidate's `_assert_provenance`, `_FakeLLM`, `_RawTool`, `_turn`, `_done`, `_fingerprint`, `_baseline_inputs` and `_capture_baseline` into the test file, with `_BASE` set to `1c9abde5bcde5fef96f2035ff319f81b0c002ff9`.
  2. Generate the golden with a throwaway script under `logs/` (gitignored). The script imports `_capture_baseline` and writes the JSON.
  3. Capture the strict baseline the same way.
  4. Use only the imports that exist on main. AD-1240 imports arrive in later milestones.
- **Premise checks:**
  - `git status --porcelain -- src` is empty during capture;
  - the import root is this worktree;
  - `manager.root` does not exist before or after capture;
  - every case stops `complete`.
- **Run:** `test_ad1240_tool_result_delivery.py::test_legacy_requests_match_pre_edit_golden`, which must pass on main.
- **Exit:** both fixtures are written, the golden test is green, and `src/` is untouched.
- **Hard stop:** any capture case does not complete, or the golden is not deterministic across two runs.

### M1. The store, the reaper and the lifecycle

- **Files:** `workspace_results.py` (row 12), `workspace_result_store.py` (row 12a), `file_access.py` (row 14: the candidate plus `is_reparse_point` only), `tests/test_ad1240_workspace_result_lifecycle.py`, and the store-level tests in `tests/test_ad1240_workspace_results.py`.
- **Do:** implement §3.1–§3.6 and §3.10. `WorkspaceResultStore` exposes the candidate's public surface:
  - `bind_agent`, `store_tool_result`, `read_tool_result_slice`, `reap_tool_results()` (**no argument**, F1), `start`, `stop`, `background_tasks`, `root`;
  - constructor: a `WorkspaceManager` (`root` is a property), `clock`, `background_register`, `sleep`, `retry`.
- **Round-2 repairs (Revision 1):**
  - F1: remove `now` from the protocol, from `UnavailableWorkspaceResults` and from the store. Delete `test_reap_refuses_a_now_ahead_of_the_store_clock`. Rewrite the invalid-clock test (`test_ad1240_workspace_results.py`) so the bad value is injected through the harness clock.
  - F2: the registry (§3.10).
  - F3: anchor settling (§3.4).
  - F5: root and namespace retry, and held-since escalation (§3.5, §3.6).
  - F6: the N5 premise.
  - F7: the log wording.
- **Round-2 tests:** F1, F2-1..4, F3-1..3, F4, R1-5(d), (e) and (f), and the N5 premise. Keep the Call 3 tests: `test_cap_deferral_and_foreign_entries_never_escalate`, the transient × broken case, and the POSIX reserved-name premise line.

  It reuses `WorkspaceManager.sanitize` and `key_for_agent` through a `WorkspaceManager` passed to its constructor, not by copying them. `GenerationReaper` owns the sweep. **Each class has ≤ 15 direct methods and a body of ≤ 500 lines.**
- **Lifecycle tests in the candidate file:**

  | Disposition | Tests |
  |---|---|
  | Keep, adapted | the restartable lifecycle and latch tests at candidate lines 87, 108, 123, 171, 194, 309, 353, 386, 442, 493, 532, 580, 630, 659, 748, 804, 905, 959, 1027 and 1158 (adapt their paths and constructors) |
  | Rewrite | `test_commit_clock_expiry_exact_boundary_and_restart_ignore_mtime` (22) becomes R2-3c. `test_partial_publication_cleanup_and_unknown_files_preserved` (52) becomes: an unadvertised partial publication is removed with its expired generation, and unknown names at the `.tool-results` root are preserved. `test_interrupted_reap_restart_keeps_positive_ownership_until_cleanup` (228) becomes `test_interrupted_generation_removal_resumes_after_restart`. `test_busy_read_crossing_expiry_refuses_before_sweep_deletes` (261) becomes a generation-expiry read refusal before any I/O |
  | Replace | `test_reaper_does_not_delete_modified_owned_payload` (213) becomes R2-3a. `test_r1_real_filesystem_retention_failure_latches_publication` (1100) becomes R1-5(b) |

- **New tests:** R1-3 (both), R1-5 (a, b, c and injected variants), R2-3, R2-3a, R2-3b (both), R2-3c, N3, N4, N5, `test_classify_os_error_table`, `test_store_source_never_overwrites_by_rename`, `test_generation_name_round_trip_and_rejects_noncanonical`, and `test_future_and_unknown_root_entries_are_preserved`.
- **Run:** both files, plus `tests/test_ad997_workspace.py`.
- **Then:** `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` (with `PYTHONPATH` set).
- **Exit:** green, and the checker exits 0.
- **Hard stops:**
  - the checker reports any new row;
  - a design point in §3.1–§3.6 cannot be implemented as written;
  - a test can pass only by sleeping on the wall clock.

### M2. Legacy-route reservation and ordinary inspection (R1-2, R2-2, R2-5)

- **Files:** `src/probos/execution/workspace.py`, `tests/test_ad1240_workspace_results.py`.
- **Do:**
  1. Port the candidate's reservation, `resolve_file` (lexical, prefix and alias refusal before `create_parents`), `list_files` and `total_bytes` pruning.
  2. Apply the R2 conditional §3 fix: compute `base` and `resolved` **once each**, check those exact values, and return only the value already checked.
  3. Apply the R2 conditional §6 fix, **as refined by the M2 cost ruling (§3.11)**: one owner/root decision per walk; `os.scandir` with no-follow `lstat`; no `resolve` for a plain regular file; resolve each directory and each link entry once; check identity at each descent; memoize only within a walk; prune before descent, emission or size computation.
  4. Acceptance uses the new R2-5 bound (≤ D + 1 + directories descended + link entries; ≤ D + 12 for the 10 × 100 fixture) and `test_resolve_count_independent_of_file_count` (R2-5b). Document the hard-link residual in a code comment.

  `WorkspaceManager` keeps ≤ 15 methods and a body of ≤ 500 lines. **No router change.** The routes are at `routers/agents.py:1484–1486`, `:1548–1550`, `:1615–1617` and `:1660–1662`; Dismiss is at `:1700–1702`.
- **Tests:**
  - R1-2, R2-2 (both) and R2-5;
  - the candidate's `test_r1_private_publication_is_confined_through_real_workspace_http`, `test_r1_resolver_listing_and_sizes_exclude_private_and_intermediate_aliases` and `test_r1_lexical_namespace_redirect_out_is_still_reserved`, adapted to the generation path;
  - `test_private_namespace_includes_malformed_and_case_variants`.
- **Run:** `test_ad1240_workspace_results.py`, `test_ad997_workspace.py`, `test_ad1021b_workspace_write.py`, `test_ad994_code_runner.py` and `test_bf758_file_read_confinement.py`, then the architecture checker.
- **Exit:** green, and the checker exits 0.
- **Hard stops:**
  - a route needs a production change to return 400;
  - the R2-5 budget cannot be met without a cache that outlives one call.

### M3. Offload core: result offload and native readers

- **Files:** `result_offload.py` (row 8), `tool_call.py` (row 9), `tools.py` (row 10), `work_item_pull_tool.py` (row 18), and the unit-level tests in `test_ad1240_tool_result_delivery.py`.
- **Do:**
  - Port `result_offload.py`, with §3.9's lexical selection and `InvocationRefusal`, `WorkspaceResultsSlot` (§3.7), and the generation segment in the preview path. Keep `_admit` sizing exact: the name is fixed width.
  - Re-apply the `tools.py` changes as **fresh edits** against main: `SourceToolResult`, `InstructionSourceToolResult`, `WorkspaceSliceToolResult`, `RecoveryFailureToolResult`, private-artifact dispatch, and the R1-4 fresh-error parity. Preserve main's `_locked_native_target` and every AD-1316 branch.
  - Port the candidate's changed regions of `tool_call.py` onto main's file, keeping main's drift.
  - **Every artifact read goes through `read_tool_result_slice`.** `tools.py` (including `_workspace_slice_result`) must not open or read artifact files itself, or it bypasses the registry (§3.3, §3.10).
- **Run:** the candidate's capture, slot and scope unit tests (`test_ad1240_workspace_results.py:37–575`, adapted), the golden test, `test_ad1148_tool_result_bounds.py`, `test_ad1187_agent_work_pull.py`, `test_ad1191_delegation_wire.py`, `test_ad1200_instruction_file_access.py`, `test_ad1316_real_effect_routes.py` and `test_bf758_file_read_confinement.py`.
- **Exit:** green; the golden is unchanged.
- **Hard stop:** keeping main's `tools.py` strict or locking behaviour conflicts with the candidate's dispatch.

### M4. Loop, dispatch and lifecycle wiring (R1-1, R1-4, R2-1, N1, N6)

- **Files:** `agentic_loop.py` (row 6), `agentic_dispatch.py` (row 5), `native_builder.py` (row 7), `runtime.py` (row 13), `startup/infrastructure.py` (row 15), `startup/results.py` (row 16), `startup/shutdown.py` (row 17), `result_offload.py` (row 8, for the C6-D1 branch only), `work_item_steps_tool.py` (row 28), `tests/test_ad1191_delegation_wire.py` (row 24), the loop-level tests in `test_ad1240_tool_result_delivery.py`, and the Phase-1 tests in `test_ad1240_workspace_result_lifecycle.py`. M4 was built as M4a (loop, dispatch, native builder) and M4b (runtime, startup, shutdown, Phase-1); round 2 carries the Call 6 rulings below.
- **Round-2 changes (Call 6):**
  - **C6-D1:** `OwnedStepsViewResult` and the `_prepare_result` branch (§3.12), with tests C6-D1-1..3. `test_ad1192_owned_steps_dm.py` must pass unchanged.
  - **C6-D2:** `delivery_remaining` (§3.9a), with the C6-D2 test.
  - **C6-D3:** apply `test_ad1191_delegation_wire.py` blob `c28c082f` verbatim (row 24). The ad1320 pin waits for M5.
  - **C6-D4.1:** the shutdown `try/finally` (row 17), with test C6-D4.1.
  - **C6-D4.2:** move M4b's AD-1240 block in `infrastructure.py` (including the `workspace_results` declaration) to immediately after `await trust_network.start()`, before `# --- Sovereign Agent Identity (AD-441) ---`. Change its comment to: "starts before the identity registry, so a failure while it starts leaves nothing else open; the unwind stops it". Tests C6-D4.2a and C6-D4.2b.
  - **C6-D5:** any R-a adaptations, under §1's rule.
  - **Small items:** the constructor keyword `workspace_results=` stays last and is assigned through the slot, guarded by `is not None`. Production callers do not pass it. The forged-view test asserts the exact error code and `stopped_reason`, which is the condition that keeps M4a's loop-level exact-type mutant classified as equivalent.
- **`agentic_loop.py` (fresh edits; the candidate's 18 hunks are a reference only). Main-side behaviour that must survive byte for byte:**
  - in `_execute_one_tool`:
    - the strict `StrictEffectPrivacyProjector` STARTED/COMPLETED projection (`:2399–2421`, `:2659–2684`);
    - `protected_logical_key`, `protected_provider_call_id` and `match_operation_handle` (`:2470–2488`);
    - `_effect_handles` bookkeeping (`:2493–2545`, `:2594–2598`);
    - the `if strict and not isinstance(trusted_correlation, EffectCorrelation): raise` re-raise (`:2604–2605`);
    - the strict refusal projection (`:2652–2658`);
    - the work-pull `ToolResultPresentation.render_complete` setup (`:2438–2465`);
    - the self_query retained-presentation branch (`:2555–2584`);
  - in `_run_scoped`: `LoopTierSteps` and the hooks (`:1282`, `:1354–1359`), budget awareness, and the `on_model_request_presented` presentation frames (`:2039–2087`), whose predicate `frame.get("content") == tool_result.output` stays as it is. **An offloaded, source or recovered presentation is never added to `PresentedToolResult`.**
- **Where AD-1240 code goes:**
  - the invocation-context and refusal decision goes **before** `:2401`;
  - capture and `prepare_result` go at **both** `ToolCallResult.from_tool_result` sites (`:2568` and `:2586`), after the effect-handle bookkeeping and the `fault_capture.record` call;
  - the final formatter, reader offer and protected compaction groups follow the candidate's design;
  - add `workspace_results = WorkspaceResultsSlot()` to the class body, and **no new method** (13 stays 13);
  - strict-profile legacy delivery per §3.8.
- **Dispatch and native builder:** after construction, assign `loop.workspace_results = resolve_workspace_results(runtime)` and merge `workspace_delivery_context(runtime, registry, agent_id)` into the run context. Confirm the in-scope view and agent-id variable names at `agentic_dispatch.py:3879`; if the scoped registry view is not in scope there, that is a hard stop. Add the R2-1 adapter at `:4111`.
- **Runtime and startup:** per rows 13 and 15–17.
  - `InfrastructureResult.workspace_results` is `WorkspaceResultStore(WorkspaceManager(config.execution.workspace_root), background_register=…)`. It starts **after `trust_network.start()` and before the identity registry** (C6-D4.2), and it is stopped in the `except BaseException` unwind of `startup/infrastructure.py`. A missing, `""`, `"."` or `Path()` root keeps the typed unavailable owner (C6-D4.3).
  - Shutdown stops the store in a `finally` inside the pools step (C6-D4.1).
  - **`reap_tool_results()` takes no argument** at startup, in the reaper loop and at shutdown (F1).
- **Phase-1 tests deferred from M1, as built (M4b report):**
  - `test_phase_one_owns_configured_root_shared_registered_reaper[register × relative]` (candidate :309; it now also publishes and reads back through the Phase-1 store);
  - `test_phase_one_failed_owner_remains_unavailable_and_drains_registration` (:353);
  - `test_shutdown_consumer_stops_workspace_after_pools[cancel]` (:386);
  - `test_phase_one_cancelled_registration_drains_owner_before_propagating` (:580);
  - `test_phase_one_missing_root_keeps_typed_unavailable_owner` (:630, six variants: `None`, `""`, `"."`, `Path()`, `42`, no execution section);
  - the `[phase1]` cases of `test_missing_anchor_terminates` (Windows, real) and `test_missing_anchor_terminates_injected` (both platforms), which carry R1-3's "owner stays unavailable" clause.

  M4b also added these extras:
  - `test_phase_one_failure_after_the_store_started_stops_it_and_reraises`
  - `test_phase_one_failure_after_a_failed_store_start_does_not_stop_the_owner_again`
  - `test_real_runtime_exposes_the_started_store_after_phase_one_and_its_rollback_stops_it`
  - `test_real_runtime_start_and_stop_run_the_store_lifecycle_end_to_end`
  - `test_shutdown_cancelled_during_the_store_stop_drains_the_worker_then_defers_the_cancellation`
  - `test_shutdown_stops_the_owner_it_excluded_from_the_sweep_not_a_later_one`
  - `test_shutdown_without_a_store_runs_to_its_end_on_the_typed_unavailable_owner`
  - `test_infrastructure_result_workspace_results_is_last_and_defaults_unavailable`
  - `test_no_production_caller_passes_an_argument_to_reap_tool_results`

  All of these must still pass after the C6-D4.2 reordering.
- **Tests:**
  - ported: R1-1, R1-4, R2-1 (with the parallel and correlation variants) and N6;
  - the candidate's loop tests (`test_ad1240_tool_result_delivery.py` candidate lines 302–1791), adapted;
  - the R1 tests at 1505, 1620, 1705 and 1791;
  - `test_actual_production_callers_bind_available_or_unavailable_owner`, which now asserts the slot assignment;
  - `test_bind_rejects_invalid_and_latches_before_callback_and_after_all_exits`, which now asserts the descriptor `__set__` refusal.
- **Run:** the full focused list (§5).
- **Exit:** green. The five R2-4 tests pass unchanged. `test_ad1324_srp_layout.py` passes unchanged. The architecture checker exits 0.
- **Hard stops:**
  - any R2-4 test, or a double from §5's list, fails without a production fallback (for example, a double with `__slots__` that rejects assignment);
  - a main-side behaviour listed above cannot be preserved;
  - `AgenticLoop` would need a 14th method.

### M5. Integration, design document and mutation campaign

- **Files:** `docs/development/workspace-tool-results.md`, the three AD-1240 test files (integration tests only), and finally `tests/test_ad1320_agentic_budget_awareness.py` (row 29, pin only).
- **Do:**
  - Add `test_raw_producer_to_workspace_to_next_request_verbatim_readback`, which crosses the seam: a real executor and observers, a real store on disk, the actual next `LLMRequest`, and a verbatim worked call returning the exact middle slice. Run it in both transcript modes.
  - Adapt the design document (row 4) and paste §9's guarantee into it. Paste its residual sentences into the reaper section: D1, F3, F4, the registry's restart residual (F2), the hard-link residual (§3.11), and the C6-D1 sentence: "A `review_requests` list above 12,288 bytes is offloaded (its content stays recoverable); only producer-typed results (`WorkPullReceipt`, `OwnedStepsViewResult`) stay inline."
  - Run the mutation campaign (§7).
  - **Run, unchanged, against the final bytes:** `tests/test_ad1192_owned_steps_dm.py` and `tests/test_ad1191_delegation_wire.py` (the latter as applied from blob `c28c082f`).
  - **List each C6-D5 R-a file** in the report, with its reason.
  - **Last of all**, after the campaign and once `native_builder.py` is frozen: update the blob pin at `tests/test_ad1320_agentic_budget_awareness.py:615` to the frozen file's LF blob (row 29). Keep the pin, and put this line immediately above it:
    `# AD-1240 (#1239): native_builder.py now assigns the workspace-results slot and merges the delivery context; the protected property (no budget_awareness in this file) is unchanged.`
    Then rerun that file.
- **First CI run (for the orchestrator).** These POSIX-premise tests run for the first time on `ubuntu-latest`, and the CI log must show them **PASSED, not skipped**:
  - `test_posix_only_entry_names_…` (its `aux` and `nul.txt` cases depend on Python 3.12's `PureWindowsPath.is_reserved`; CI pins 3.12, `.github/workflows/ci.yml:47`);
  - `test_posix_fifo_…`;
  - the symlink variants;
  - the real variant of F3-2;
  - F4.

  There is no Linux runner on the Captain's machine.
- **Exit:**
  - the full focused list (§5) is green;
  - the campaign table is filled, with every row that §7 marks must-kill KILLED;
  - the probes are read and every REQUIREMENT case is ported; list the mapping in the report.

---

## 5. Focused test list (M4 and M5 exit)

Run every file with `-n 0`, with `PYTHONPATH` set and the import root checked.

```
tests/test_ad1240_tool_result_delivery.py
tests/test_ad1240_workspace_result_lifecycle.py
tests/test_ad1240_workspace_results.py
tests/test_ad1209_work_item_status.py tests/test_ad1226_recall_artifact.py tests/test_bf731_captain_llm_lane.py
tests/test_ad1007_capability_gate.py tests/test_ad1142_crew_child_compaction.py tests/test_ad1155_loop_until_done.py
tests/test_ad1180_agentic_disposition.py tests/test_ad1147_parallel_tools.py tests/test_ad1189_deferred_tool_schemas.py
tests/test_ad1190_delegation_tree_budget.py tests/test_ad1205_fault_paths.py tests/test_ad1208_cost_bounded_turns.py
tests/test_ad1228_standing_interests.py tests/test_ad1229_message_receipts.py tests/test_ad1229_message_receipts_e2e.py
tests/test_ad1241_mcp_offer_budget.py tests/test_ad1322_economic_judgment_integration.py
tests/test_ad1324_srp_layout.py tests/test_ad1270b_architecture_fitness.py
tests/test_ad1146_multiturn_messages.py tests/test_ad1148_tool_result_bounds.py tests/test_ad1151_durable_tool_outputs.py
tests/test_ad1152_agentic_correlation.py tests/test_ad1152_crew_token_usage.py tests/test_bf760_trace_records_the_tools_length.py
tests/test_ad1187_agent_work_pull.py tests/test_ad1191_delegation_wire.py tests/test_ad1192_owned_steps_dm.py
tests/test_ad1200_instruction_file_access.py tests/test_ad1200_repository_instructions.py
tests/test_ad1200_repository_instruction_transport.py tests/test_ad1200_repository_instruction_wire.py
tests/test_ad1213_delegated_approvals.py tests/test_ad1214_decision_pre_clearance.py
tests/test_ad1260_wellness_domain.py tests/test_ad1261_authority_domain.py
tests/test_ad1315_protected_execution_authority.py tests/test_ad1316_governed_effect_broker.py tests/test_ad1316_real_effect_routes.py
tests/test_ad1320_agentic_budget_awareness.py tests/test_ad1321_value_stakes.py
tests/test_ad1323_continue_extension_costed_continue_ask.py tests/test_ad1323_continue_extension_e2e.py
tests/test_ad1323_continue_extension_permits.py tests/test_ad1323_continue_extension_restart.py tests/test_ad1323_continue_extension_seam.py
tests/test_ad1325_boundaries.py tests/test_ad1325_completion_chain.py tests/test_ad1325_economic_calibration.py
tests/test_ad997_workspace.py tests/test_ad1021b_workspace_write.py tests/test_ad994_code_runner.py tests/test_bf758_file_read_confinement.py
tests/test_issue1419_failed_start_rollback.py tests/test_ad1270f_shutdown_grace.py tests/test_ad824_shutdown_hygiene.py
```

The last line was added in Call 7, because C6-D4 relies on those files passing **unchanged**, the BF-882 pins included.

Then run `scripts/check_architecture_principles.py --check`. Report collected, passed and skipped counts per file. Every skip must be one of §0.7's platform skips.

---

## 6. Hard stops: the Builder must not decide these

Stop and report to the orchestrator, who routes the report to the Architect, if any of the following happens:

1. A tracked path outside §2's footprint (24 paths plus the C6-D5 row-30+ files) needs an edit.
2. `architecture-baseline.yaml` or the AD-1324 pins would need to change, or the checker reports a new row.
3. `AgenticLoop` would need a new method, or a test double needs a production fallback (`getattr` guard, conditional binder).
4. Any threshold, encoding, limit, the 24 h read expiry, `GENERATION_SECONDS`, the retry numbers, the taxonomy codes, or a constructor or request golden would need to change.
5. Publication needs `os.replace` or `rename`, or removal needs `rmtree`, or would follow a link.
6. `high_water` would need to be restored from disk.
7. The strict profile would need to offload.
8. Main-side behaviour named in §2 or §4.M4 cannot be preserved.
9. Any R2-4 test, or any file in §5, fails, and the fix is not inside the milestone's files.
10. A premise assertion fails: the test setup does not reach its boundary.
11. A test can only pass by sleeping on the wall clock, or by skipping on both platforms.
12. A rollback path would reopen raw namespace access, or delete workspaces or original sources.
13. Any class would exceed 15 direct methods or a 500-line body (`WorkspaceResultStore`, `GenerationReaper`, `ArtifactIO`, `CommittedArtifacts`, `WorkspaceManager`, and every other new class).
14. A read of anything under `.tool-results` would bypass `read_tool_result_slice`, and so the registry.
15. `file_access.py` would need any change beyond `is_reparse_point`.
16. `reap_tool_results` would need a time argument, or a sweep would need a time read outside the store lock.
17. A failure would have to be settled against anything other than the anchor chain (§3.4), or a root or namespace failure would bypass the retry runner.
18. The registry would have to be durable, or have to refuse unregistered artifacts after a restart.
19. A third producer exemption would be needed beyond `WorkPullReceipt` and `OwnedStepsViewResult`, or an exemption would have to key on a tool id, a metadata key or text (§3.12).
20. **C6-D5 stop conditions.** A test file fails because production callers are armed-unavailable, and any of these holds:
    - the test's subject is the large-result path: it pins truncation or destroy-on-overflow for a production caller (the AD-1191 pattern, which needs a per-file Architect ruling);
    - more than **8** files need R-a adaptation;
    - the failure is of any other kind;
    - the fix would need a production change, a shared-fixture edit, a skip or xfail, a threshold change, unarming, or a `getattr` fallback.
21. Shutdown would need a new guarded step, or the BF-882 pins (`tests/test_issue1419_failed_start_rollback.py`) would need editing; or Phase 1 would need an identity-registry stop added to main's unwind.

---

## 7. Mutation campaign (M5, one campaign, run by the Builder)

**Procedure:**
1. Pin the bytes first, **after all Revision-1 repairs have landed**: record the sha256 of `workspace_results.py`, `workspace_result_store.py`, `workspace.py`, `file_access.py` (it now carries `is_reparse_point`), `result_offload.py`, `agentic_loop.py` and `work_item_steps_tool.py` (it now carries `OwnedStepsViewResult`). Re-record each of them after the Call 6 round-2 repairs land.
2. Run the baseline once: the three AD-1240 files must be green.
3. Mutate in place with a `.mutbak` sibling, using **single-line anchors only**. The tree uses CRLF, so match one physical line.
4. Classify each mutant:
   - an anchor that does not match is **INERT**, which is not killed: fix the anchor and rerun;
   - a run that exceeds 600 s is **INVALID**, which is not survived;
   - a surviving mutant is a weak test, but only after you confirm the mutant reaches the behaviour it claims to break.
5. Restore and re-hash after each mutant.
6. Report the base tree, each file's sha256 and a per-row verdict. This is the campaign of record. A file whose hash later differs requires its rows to be rerun.

| # | File | Anchor (the line §3 requires) | Mutation | Must be killed by |
|---|---|---|---|---|
| 1 | `workspace_result_store.py` | `if now >= generation_expiry(name):` | `>=` → `>` | R2-3c (boundary sweep at exactly `end(G) + R`) |
| 2 | same | same | `generation_expiry(name)` → `generation_expiry(name) - RESULT_RETENTION_SECONDS` | R2-3a |
| 3 | same | `if GENERATION_NAME_RE.fullmatch(name) is None:` | `is None` → `is not None` | `test_future_and_unknown_root_entries_are_preserved` |
| 4 | `workspace_results.py` | `return generation_start(name) + GENERATION_SECONDS + RESULT_RETENTION_SECONDS` | delete `+ GENERATION_SECONDS` | R2-3c and N3 |
| 5 | `workspace_result_store.py` | the rollover check `if committed_at >= generation_start(generation) + GENERATION_SECONDS:` | → `if False:` | N3 |
| 6 | same | `committed_at = max(clock_value, generation_start(generation), self._high_water)` | drop `self._high_water` | N4 |
| 7 | `workspace_result_store.py` | `artifact.publish_file("manifest.staged", "manifest.json")` | → `__import__("os").replace(artifact.path / "manifest.staged", artifact.path / "manifest.json")`. This must be a **valid** mutant: the store does not import `os`, so a bare `os.replace` would be killed for the wrong reason, by a `NameError` | `test_store_source_never_overwrites_by_rename`, plus `test_publication_never_overwrites_a_manifest_that_already_exists` |
| 8 | `file_access.py` | `flags = os.O_WRONLY \| os.O_CREAT \| os.O_EXCL` | drop `\| os.O_EXCL` | `test_pin_public_io_and_atomic_no_overwrite` |
| 9 | `workspace_result_store.py` | `return "transient"` (in `classify_os_error`) | → `return "integrity"` | R1-5(b), both variants |
| 10 | same | `return "integrity"` (the last line of `classify_os_error`) | → `return "transient"` | R1-5(a) |
| 11 | same | the escalation line `if now >= generation_expiry(name) + RESULT_RETENTION_SECONDS:` | → `if False:` | R1-5(c) |
| 12 | same | the link guard `if is_reparse_point(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):` | → `if False:` | R2-3b, both variants |
| 13 | `workspace_result_store.py` (read) | the pre-I/O `if clock_value >= generation_expiry(generation):` | → `if False:` | R2-3c and the generation-expiry read test |
| 14 | same (read) | `if clock_value >= reference.expires_at:` (the first occurrence) | `>=` → `>` | R2-3c (`result_expired` at exactly `committed_at + R`) |
| 15 | `workspace.py` | the final-value reservation check in `resolve_file` | → `if False:` | R2-2 and R1-2 |
| 16 | `result_offload.py` | the lexical `select` before the registry | moved after `bind()` (two-line move; record it as a two-anchor mutant) | R2-1 |
| 17 | `workspace_result_store.py` | `if tally.transient > transient_before:` | → `if tally.deferred > deferred_before:` | `test_cap_deferral_and_foreign_entries_never_escalate` |
| 18 | same (read) | `if recorded is not None and recorded != _Committed.of(reference, owner_digest):` | → `if False:` | F2-1 and F2-2 |
| 19 | same | `if not _chain_intact(anchor):` (in `_settle`) | → `if False:` | F3-2 (injected variant) |
| 20 | same | `if now - self._held_since[path] >= RESULT_RETENTION_SECONDS:` | → `if False:` | R1-5(f) |
| 21 | same | re-anchored (C9 A1-5): `self._identities.remember(runner.run(partial(self._probe, existing), _transient))` | `_transient` → `lambda exc: False` | R1-5(e): `test_root_transient_defers_without_latch[probe]` and `test_transient_failure_at_context_exit_is_retried[root-probe]` |
| 22 | `workspace.py` | recorded from the implementation: `if not child.link and not child.is_dir:` (in `_checked_entry`) | → `if False:`, so every entry is resolved | R2-5 and R2-5b: `test_ordinary_inspection_resolve_budget`, `test_resolve_count_independent_of_file_count` |
| 23 | same | `if entry.name.casefold() == RESULT_DIRECTORY:  # the reserved name, in any case` (in `_children`) | → `if False:` | corrected (A2): `test_case_variants_of_the_namespace_name_are_pruned_by_name` (2 cases) and `test_r1_lexical_namespace_redirect_out_is_still_reserved[inside]`. The originally named `test_private_namespace_includes_malformed_and_case_variants` does **not** kill it: it never runs the walk |

| 24 | `result_offload.py` | `if type(raw) is OwnedStepsViewResult and raw.error is None:` | → `if False:` | C6-D1-1 |
| 25 | same | same line | → `if isinstance(raw, ToolResult) and raw.error is None:` | C6-D1-2 (and C6-D1-3) |
| 26 | `agentic_loop.py` | `self._max_iter - counted_iterations - (1 if _counts_toward_max_iterations(tool_uses) else 0),` (the counted term inside `min(` in §3.9a) | → `delivery_remaining,`, which turns the `min` into a no-op | C6-D2 case (b) |
| 27 | same | `delivery_remaining = iteration_ceiling - iteration - redo_calls` | `iteration_ceiling` → `self._max_iter` | C6-D2 case (a) |
| 28 | `agentic_dispatch.py` | `or (tid == "read_file" and _recovery_reader_full)` | → `or False` | the four `test_deferred_schemas_never_withhold_the_promised_reader` / `test_deferred_schemas_with_mcp_offer_never_withhold_the_promised_reader` cases |
| 29 | `result_offload.py` | `context.run.scope.reserve_workspace(reference)` | → `pass` | `test_workspace_promise_refuses_replaced_reader_before_invocation` (25 tests failed) |
| 30 | same | `if Path(path).is_absolute() and self.scope.workspace_promised(path):` | → `if False:` | the replaced-reader matrix, including its resolver-counter assertions (16 tests failed) |
| 31 | same | re-anchored (review round 4): `if target != Path(os.path.normpath(path)): raise WorkspaceResultError("source_changed")` | `if False: …` | only the four `resolver_answers_differently` cases of the replaced-reader matrix and the two `resolves_elsewhere` controls of the equivalent-spelling matrix (Builder B: the three ruled losses refuse at `ReaderIdentity.matches` first, so a fourth loss was added; the matrix is 16 cases) |
| 32 | `agentic_dispatch.py` | `_delivery_armed = plan_mode_tool_ids is None or "read_file" in plan_mode_tool_ids` | → `_delivery_armed = True` | the two `test_plan_mode_keeps_legacy_delivery` cases |
| 33 | `workspace.py` | `info = os.lstat(directory)  # no-follow: os.stat would report the identity of what an alias leads to` | `os.lstat` → `os.stat` | 21 failures: `test_ordinary_walk_does_not_enter_a_directory_replaced_by_an_alias_to_the_same_object`, `test_overview_route_does_not_list_a_directory_replaced_by_an_alias_to_the_same_object` (route cases), `test_ordinary_walk_skips_a_directory_that_cannot_be_examined_when_entered` |
| 34 | same | `opaque = child.is_dir and not child.link and child.name in _OPAQUE_DIRS  # a link's target is never sized` | drop `not child.link and` | `test_links_inside_the_owner_folder_are_listed_once_and_never_entered`, `test_links_are_never_entered_on_a_filesystem_without_identities` |
| 35 | `workspace_result_store.py` | `deferred_before = tally.deferred` | append `; self._committed.evict_generation(namespace, name)` | `test_deferred_generation_keeps_its_commitment_record` |
| 36 | same | the success-branch `self._committed.evict_generation(namespace, name)` | → `pass` | `test_registry_bucket_evicted_with_its_generation` |
| 37 | same | `if existing == self._root and self._identities.knows(self._root):` | → `if False:` | `test_remembered_anchor_missing_is_an_integrity_failure[root]` |
| 38 | same | `if self._identities.knows(namespace):` | → `if False:` | `test_remembered_anchor_missing_is_an_integrity_failure[namespace]` |
| 39 | same | `for name in _rotated(names, self._capped_at.get(namespace)):` | → `for name in sorted(names):` | `test_capped_sweeps_rotate_to_later_generations[generation]` |
| 40 | same | `for key in _rotated(names, self._capped_at.get(self._root)):` | → `for key in sorted(names):` | `test_capped_sweeps_rotate_to_later_generations[owner]` |
| 41 | same | `identities, names = runner.run(partial(self._listed, namespace), _transient)` | `_transient` → `lambda exc: False` | `test_transient_failure_at_context_exit_is_retried[namespace-listing]` |
| 42 | same | `identities, names = runner.run(partial(self._listed, self._root), _transient)` | same | `test_transient_failure_at_context_exit_is_retried[root-listing]` |
| 43 | `result_offload.py` | `if target != Path(os.path.normpath(path)): raise WorkspaceResultError("source_changed")` (review round 4) | `Path(os.path.normpath(path))` → `Path(path)` | exactly the two `test_workspace_promise_equivalent_spelling_recovers_through_the_unchanged_reader` cases (`[plain]`, `[structured]`) |
| 44 | `workspace.py` | `is_dir, link = _classify(entry, info)  # a directory replaced since the scan is what is there now` (the second call, in `_children`; review round 4) | delete the line | exactly six cases: `test_a_directory_seen_as_a_link_at_its_fresh_observation_is_listed_once_and_never_sized_or_entered` (the injected variant on both platforms and the real-junction variant on Windows, each for listing and size) and `test_a_directory_seen_as_a_file_at_its_fresh_observation_is_listed_as_a_plain_file` (listing and size); the control `test_a_directory_still_a_directory_at_its_fresh_observation_is_sized_and_entered_as_before` passes |

Rows 1–14 and 17–44 must be KILLED. Rows 15–16 must be KILLED or justified. The anchors of rows 17–21, 23–32 and 35–42 are lines this contract requires to exist (§3.3, §3.4, §3.5, §3.6, §3.9a, §3.11, §3.12, §3.13). If the implemented line differs, stop and report it rather than editing the anchor to match. Rows 22, 33, 34, 43 and 44 were recorded from the implementation.

**Campaign of record for rows 21–42** (each run on a scratch copy or in memory, each restore verified by hash; Builder-reported sha256 prefixes, not recomputed in Call 10): rows 28–32 against `agentic_dispatch.py` `370126d497f0`, `result_offload.py` `2ee8feb44f98`, `workspace_results.py` `d9de1642eb1c` (Builder B); rows 21 and 35–42 against `workspace_result_store.py` `32bf1874ace9` (Builder A1); rows 22, 23, 33 and 34 against `workspace.py` `2f35cd9698e2` (Builder A2). All KILLED. Rerun a row whose file's hash differs. Index blob ids at Call 10 are in addendum 3.

**Rerun after review round 4 on the final bytes** (scratch copies, each restore hash-verified): rows 16, 24, 25, 29, 30, 31 and 43 against `result_offload.py` `9506d0a7d7f4` (Builder c3da7d9d; row 25 needed `test_delivery_scope_is_closed_on_every_exit[cancelled]` deselected, because under that mutant it waits for a second request that never comes instead of failing: an unbounded wait in an existing test, noted for follow-up); rows 15, 22, 23, 33, 34 and 44 against `workspace.py` `213c3f99f658` (Builder 8c398189; two docstrings were corrected after review round 5, the docstring-stripped AST is identical, and the hash is now `e2d30a01f1e2`). All KILLED. The M5b rows for files that did not change since (`workspace_result_store.py` `32bf1874ace9`, `workspace_results.py` `d9de1642eb1c`, `file_access.py`, `agentic_loop.py`, `work_item_steps_tool.py`) stand.

**Campaign of record for rows 1–20 and 24–27** (M5b, 2026-10-12, Builder a115da3f on a scratch copy; live and scratch hashes matched at the start and at the end; baseline of the three AD-1240 test files 922 passed, 20 skipped): all 24 rows KILLED; none SURVIVED, INERT or INVALID, and no kill was an import, collection, setup or `NameError` failure. Pinned sha256 (first 12 hex): `workspace_results.py` D9DE1642EB1C, `workspace_result_store.py` 32BF1874ACE9, `workspace.py` 2F35CD9698E2, `file_access.py` 10DD60DAF646, `result_offload.py` 2EE8FEB44F98, `agentic_loop.py` 1910A452CCE6, `work_item_steps_tool.py` 604A224F1714. Interpretations the Builder recorded: row 14 mutates the first of the two occurrences of its anchor; row 15's anchor is `if is_workspace_result_path(base) or is_workspace_result_path(resolved):` in `resolve_file`; row 16 is two single-line edits in `result_offload.py` (the lexical `select` line becomes `directive = None`, and the `bind()` line gains `directive = self.scope.select(path) if Path(path).is_absolute() else None`), killed by the promise-survival tests; row 25's replacement uses `__import__("probos.tools.protocol", fromlist=["ToolResult"]).ToolResult`, because `ToolResult` is not imported in that module. The POSIX-only variants are skipped on Windows and first run on `ubuntu-latest`.

---

## 8. Do not build

- Strict-profile offload (§3.8; considered and deferred).
- Identity-bound removal primitives (`remove_file(expected=…)`), handle-bound deletion, `FileDispositionInfo` calls, and any remover for names the pinned primitives refuse (D1).
- A durable or on-disk registry, key or ledger for committed artifacts; any registry beyond the in-process `CommittedArtifacts` (§3.10).
- Any relocation-preventing boundary for POSIX directory descriptors (F4).
- A `now` or other time parameter on `reap_tool_results`.
- A general "complete-by-contract stays inline" rule, an exemption keyed on a tool id or metadata, or a special threshold for any producer (C6-D1 rejected all three).
- Leaving a loop unarmed when a runtime lacks the `workspace_results` attribute (C6-D5 rejected this).
- An identity-registry stop in Phase 1's unwind (C6-D4.2 chose the reordering instead).
- Quarantine or claim journals, or a `publication.json` reaping marker.
- Tier-2 isolation, or any sandboxing of `run_python`.
- Producer retry, or retrying a failed publication beyond the single rollover retry.
- New thresholds, encodings, limits, config fields, tools, events, `stopped_reason` values, HXI or router changes.
- Any edit to `docs/development/architecture-baseline.yaml`, `tests/test_ad1324_srp_layout.py` or `reply_value.py`.
- **Trackers.** `DECISIONS.md`, `PROGRESS.md`, `docs/development/roadmap.md`, `open-ads-report.md` and `ad-ledger-snapshot.json` are edited only at ship, by the orchestrator.

---

## 9. Revised guarantee (paste into the design doc in M5; the orchestrator copies it to DECISIONS at ship)

> `.tool-results` is a runtime-reserved directory whose contents may be removed once their retention has expired. Large results are published into hourly generation directories, each named by the UTC hour of the injected clock (`YYYYMMDDTHHZ`). Every artifact's directory and files are created exclusively and never rewritten, and every committed artifact's `committed_at` falls inside its generation's hour. Reads return the exact committed text until `committed_at + 24 h` and refuse it with `result_expired` from then on. The reaper removes only whole generations whose hour ended at least 24 h ago, and decides this from the name and the clock alone, so ProbOS's own writers cannot race it and no ProbOS-produced artifact is removed before its retention expires; physical removal follows within about one hour plus one sweep. Each sweep samples the clock once, inside the store lock, and decides every removal in it from that sample; a clock that steps backwards while a sweep is already removing does not stop that sweep. ProbOS does not preserve anything that a process outside ProbOS writes or substitutes inside the directory, and Tier-1 code execution, which is not sandboxed (AD-993), counts as outside ProbOS. Inside an expired generation such content is removed with the generation. While a generation is unexpired and the running ProbOS process still holds its commitment record, a read refuses a payload, outline or manifest that differs from what the process committed in its digest, sizes, outline hash, `committed_at`, representation or owner digest (manifest keys it did not write are not compared); without that record (after a restart, or once the generation has been removed whole), a read can check only that the payload, outline and manifest agree with one another, so a consistent rewrite by a writer with ProbOS's own OS identity is not detected then, and no artifact is ever readable past the end of its generation's hour plus 24 hours, which is decided from the directory name alone. The reaper never follows links. Brief Windows sharing violations and their POSIX equivalents are retried within a bounded budget and deferred to the next sweep without switching offload off. Publication is latched until a completed `stop()` and a successful `start()` only by an integrity failure, by a generation that still cannot be removed because of a transient failure one further retention period after it expired, by a root or owner-namespace directory that has stayed unopenable for one retention period, by a sweep that raises or is cancelled, by the reaper task ending or being cancelled, or by a `start()` that fails or is cancelled. Private-path, foreign-owner and expiry refusals on every legacy workspace route remain.

**Residual sentences** (they go in the design document's reaper section and in the DECISIONS residual list):

> An entry inside an expired generation that the pinned filesystem primitives refuse to touch — a link, a junction, a special file, or a name they reject, such as one containing `:` or `\` or ending in a dot or space — is left in place, counted as skipped, and keeps its generation directory on disk; ProbOS never creates such entries, so they come only from a process outside ProbOS, the material retained is bounded by what that process wrote, and it never latches publication.

> An entry inside an expired generation whose identity changes while the reaper removes it is treated as content placed there by a process outside ProbOS when the pinned primitives report an identity change or a refused name and the chain from the workspace root to the owner's `.tool-results` directory still verifies: it is removed or left for the next sweep and never latches. With that chain intact, any other error from such an entry that is neither already-gone nor transient (for example `ENOTDIR`, `EACCES` or `EIO`) is an integrity failure and latches publication, and so is a change anywhere in that chain.

> On POSIX, removal acts on directory objects that were verified to be inside the expired generation when they were opened, not on their current pathnames; a process outside ProbOS that moves such a directory elsewhere during removal can have entries removed from it at its new location, and the reaper's next check then treats the change as foreign (inside the generation) or as an integrity failure (above it).

> A hard link created by a process outside ProbOS is indistinguishable from an ordinary file and is listed and served as one.

> A `review_requests` list above 12,288 bytes is offloaded (its content stays recoverable); only producer-typed results (`WorkPullReceipt`, `OwnedStepsViewResult`) stay inline.

> A sweep decides every removal from the one clock sample it takes inside the store lock; if the clock steps backwards while that sweep is removing, an artifact it removes may be one that a reading of the stepped-back clock would still call unexpired. Reads are serialized with sweeps, so no read observes the clock in the middle of a sweep.

> A generation's commitment record is dropped only when the generation has been removed whole or found already gone; a generation whose removal is deferred, capped or held keeps it until it is removed or the process restarts. Once a generation has been removed whole its record is gone, so if the clock steps back far enough for the generation's name to read as unexpired again, an artifact that a process outside ProbOS places there is read with the restart-grade consistency check only; and a generation directory that a process outside ProbOS removes before its expiry is never listed again, so its record stays in memory until the process ends.

> Inside one expired generation the walk runs in name order, so ProbOS artifacts listed after at least 10,000 retained foreign entries in that same generation stay on disk with it; and a sweep that walks that many entries holds the store lock, delaying publications and reads, for the length of the walk (measured at 10,000 entries from about 10 seconds to over 35 seconds, depending on the host's load; this is not a bound).

> A root or owner namespace that disappears while ProbOS is stopped is treated after the restart as never created.

> The ordinary workspace walk observes only a directory's own final component before entering it; an ancestor swapped for an alias to the same object between a scan and a child's descent could still expose that child's plain-file names and sizes.

> Two ProbOS processes on one workspace root are not promised: the store lock, the high-water mark, the registry and the identity cache are per process, and an artifact's margin against another process's clock is `end(G) − committed_at`, which is near zero for an artifact committed late in its hour.

---

## 10. Ship-time notes (for the orchestrator, not the Builder)

- **DECISIONS.md, AD-1240 entry:**
  - §9 verbatim;
  - the **C1 disclosure**: Tier-1 `run_python` counts as outside ProbOS, because `code_runner.py:489` uses the owner workspace as its working directory and AD-993 is confinement-by-convention. The Captain may still change this sentence;
  - the **2R decision**: escalation latches publication at `generation_expiry + 24 h`, and only for a transient hold. It is reversible to warn-only, with the residual stated in §3.6;
  - the **root and namespace escalation (F5)**: a root or owner-namespace pin or listing that stays deferred for one retention period latches. It is reversible to warn-only; without it, retention could stop forever while only log lines record it;
  - **accepted residuals** (paste the §9 residual sentences, plus these):
    - D1: foreign entries the primitives refuse are retained with their generation and reported as skipped; they never latch; foreign entries in one expired generation can delay, but not prevent, the removal of other generations, because a capped sweep resumes after the generation and the owner where its entry budget ran out;
    - F3: an entry inside an expired generation whose identity changes while the reaper removes it is treated as content placed there by a process outside ProbOS when the pinned primitives report an identity change or a refused name and the chain from the workspace root to the owner's `.tool-results` directory still verifies: it is removed or left for the next sweep and never latches. With that chain intact, any other error from such an entry that is neither already-gone nor transient (for example `ENOTDIR`, `EACCES` or `EIO`) is an integrity failure and latches publication, and so is a change anywhere in that chain;
    - F4: POSIX removal is confined to directory objects, not pathnames;
    - hard links created outside ProbOS are indistinguishable from ordinary files;
    - namespace-level and root-level transient deferral logs a WARNING every sweep and escalates only after one retention period (F5, which supersedes the Call 3 "never escalates" note);
    - F2's restart residual: after a restart, only consistency between the payload, outline and manifest is checked, bounded by `generation_expiry` from the name;
    - when removing the staged manifest fails, the `publish_file` primitive skips its POSIX directory `fsync`; no crash-durability claim is made, because offload references are invocation-scoped;
    - an outsider deleting a still-unexpired generation leaves two cached identities per published generation (the generation directory and each agent directory) that are never evicted, so publication into that generation fails for the rest of its hour;
    - a failed recovery read through a reader that is not in the dispatch offer is labelled unknown in AD-1248 failure summaries (C8);
  - **armed-unavailable policy (C6-D5):** every production caller is armed. With no started store, a result above 12,288 bytes stops the run with `workspace_unavailable` rather than being truncated, which keeps the ratified rule that missing production ownership never silently chooses legacy. Tests that tripped over it only by an incidental vector size received the pre-authorised minimal adaptation (R-a); list those files at ship;
  - **owned-steps exemption (C6-D1):** AD-1192 pages (≤ 16 KiB) stay inline, identified only by the producer-owned `OwnedStepsViewResult`, because their exact text authorises acknowledgement. This is the second producer exemption, beside `WorkPullReceipt`; a `review_requests` list above the threshold is offloaded and stays recoverable;
  - **Phase-1 ordering (C6-D4.2):** the result store starts after the trust network and before the identity registry, so a failure while the store starts leaves no identity-registry connection open, and main's unwind is unchanged apart from stopping the store; shutdown stops the store in a `finally` inside the pools step (C6-D4.1);
  - strict profile considered and deferred; plan mode whose allowlist excludes `read_file` keeps legacy delivery (C8-F1).
- **Captain-facing disclosures** (the PR body quotes this list):
  - **C1:** Tier-1 code execution counts as outside ProbOS (the C1 sentence in §9); the Captain may still change it.
  - **Armed-unavailable (C6-D5):** with no started store, a result above 12,288 bytes stops the run with `workspace_unavailable` rather than being truncated. One production caller is in that state by construction: the crew verifier's session-correction runtime projection (`_SessionCorrectionRuntime`, `crew_verifier.py`), a deliberately narrow frozen set of attributes with no workspace store (found in review round 4; unchanged from the base). Giving it an owner is a follow-up.
  - **Inline exemptions:** `OwnedStepsViewResult` (owned-steps pages; the 16 KiB cap bounds the view JSON, so a rendered page can reach about 16.8 KB) and `WorkPullReceipt` (work pull) stay inline; nothing else does.
  - **Legacy delivery:** the strict profile, and plan mode (the AD-1156 allowlist excludes `read_file`), keep legacy delivery, each with one INFO log; their results are not covered by the recoverability guarantee.
  - **Clock sample (C9 A1-1):** each sweep samples the clock once, inside the store lock, and decides every removal in it from that sample; a clock that steps backwards while a sweep is already removing does not stop that sweep.
  - **Permission-class latch (a decision the Captain can change):** a persistent `EACCES`, `EPERM`, `EROFS` or `EIO` while removing an expired generation, with the anchor chain intact, is an integrity failure and latches publication until a completed stop and a successful start.
  - **D-B2** was already merged separately.
- **Ship-time facts (corrected in Call 10):**
  - footprint: 26 paths in the index (16 source files, 6 test files, 2 fixtures, the design document and this contract). `tests/test_ad1125_room_bound_execution.py` is the C6-D5 (R-a) file; `tests/test_ad1320_agentic_budget_awareness.py` carries the C6-D3 pin move (native_builder.py blob `24179141cc441e31e176227fc767b39b950ac976`, with the inline reason). Calls 8 and 9 and the repairs A1, A2 and R4 added no path;
  - POSIX-premise skips on Windows: 15 cases in 8 test functions at M5a (6 in lifecycle, 1 in results, 1 in delivery), not ten. After the review-3 repairs the Windows run of the three AD-1240 files skips 20 cases in 10 test functions (lifecycle 12 cases in 6 functions, results 6 in 3, delivery 2 in 1; measured by the orchestrator on 2026-10-12 with `pytest -v`), and passes 922; the first CI run is the count of record;
  - method counts: `GenerationReaper` 15 (the checker flags above 15), `SourceRecoveryScope` 8, `DeliveryRun` 10, `AgenticLoop` 13, `WorkspaceManager` 9.
- **PROGRESS.md facts:**
  - AD-1240 shipped, #1239;
  - hourly generations with 24 h read retention and physical removal within about 25 h;
  - the transient-versus-integrity latch, with the 2R and root/namespace escalations;
  - the in-process committed-artifact registry (seven fields);
  - the owned-steps exemption, and delivery's iteration accounting under AD-1208 (C6-D2);
  - 26 paths in the index, including the C6-D5 test file and the C6-D3 pin move (`file_access.py` gains the pinned-directory primitives `PinnedDirectory`, `pin_directory`, `read_verified_file` and `is_reparse_point`; `work_item_steps_tool.py` gains only `OwnedStepsViewResult`);
  - the R1 and R2 acceptance set, with R2-3 as documented behaviour;
  - the mutation campaign of record;
  - the gate receipt path.
- **Regeneration.** Editing `DECISIONS.md` or `PROGRESS.md` requires `scripts/gen_ad_ledger.py` regeneration (`gen_ad_ledger.py:20–31`), which rewrites `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`. Commit all four together. A roadmap Bug Tracker row is not needed, because no BF is filed.

---

## Tracking

Ship-time only (§10). The Builder edits no tracker.

## Acceptance criteria

- Every §1 row has its named test, passing on Windows, with the CI-platform variant passing on `ubuntu-latest`. No test skips on both platforms.
- The five R2-4 tests and `test_ad1324_srp_layout.py` pass unchanged. `check_architecture_principles.py --check` exits 0.
- The golden re-captured in M0 is unchanged through M5.
- The mutation campaign of record is complete, with rows 1–14 and 17–27 KILLED.
- Every REQUIREMENT probe case is ported, with its premise asserted first. R2-3 is replaced by the documented-behaviour test, whose docstring quotes the sentence in §1 exactly.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-10-11, `origin/main` `1c9abde5`)

```
git log -1 --format="%H %s"
  1c9abde5bcde5fef96f2035ff319f81b0c002ff9 Merge pull request #1507 ...
git rev-parse refs/preserved/ordinary-1239-e38710b8 refs/preserved/ordinary-1239-e38710b8^{tree}
  5f7c7c591215d9eee773440257b6783a16fb6949
  e38710b8c6691f0c3c7ab70dea4546af410d4233
Glob logs/probes/*.py
  logs\probes\probe_1239_review_r1.py, logs\probes\probe_1239_review_r2.py
git diff --stat 0ae79d95 e38710b8
  27 files changed, 6517 insertions(+), 98 deletions(-)
git diff --stat 0ae79d95 HEAD -- <candidate source/test paths>
  agentic_dispatch.py +2041, agentic_loop.py +1321, native_builder.py +27, tool_call.py 15, tools.py +304,
  runtime.py +362, startup/infrastructure.py +114, startup/results.py +14, startup/shutdown.py +1062,
  test_ad1142 41, test_ad1155 173; workspace.py, file_access.py, work_item_pull_tool.py,
  test_ad1007, test_ad1180, test_ad1191: no change
grep "^class |^    (async )?def " src/probos/cognitive/swe_harness/agentic_loop.py
  1254 class AgenticLoop; methods at 1257,1363,1385,1406,1418,1434,1447,1519,2154,2244,2362,2687,2696 (= 13)
tests/test_ad1324_srp_layout.py
  19: ARCHITECTURE_BASELINE_SHA256 = "62ceb51a..."   22: ("swe_harness/agentic_loop.py", "AgenticLoop", 13)
  50-51: test_agentic_loop_keeps_the_pre_ad1324_method_ceiling ... <= 13
scripts/check_architecture_principles.py
  187: SRP_MAX_BODY_LINES = 500   188: SRP_MAX_DIRECT_METHODS = 15   566-569: triggers lines/methods
docs/development/architecture-baseline.yaml
  650: key: probos.cognitive.swe_harness.agentic_loop::AgenticLoop (triggers: lines); no WorkspaceManager row
candidate workspace.py (git show ...:src/probos/execution/workspace.py)
  187 class WorkspaceManager; 27 direct defs from 190 to 791 (both SRP triggers)
  67-69 _RESULT_FILES incl. "publication.json"; 611 now < committed_at + R; 636-644 reaping marker then pathname deletes
candidate agentic_loop.py: 926 def bind_workspace_results (the 14th method on main)
candidate file_access.py
  450 class PinnedDirectory; 551 flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL; 579 publish_file via os.link;
  597 remove_file; 607 remove_directory; 659 pin_directory
src/probos/execution/workspace.py (main): 101 class WorkspaceManager; 155 resolve_file; 199 list_files; 244 total_bytes; 18 Tier-1 note
src/probos/agents/code_runner.py:489  return self._workspace_manager().resolve(owner, create=True), True
src/probos/cognitive/swe_harness/agentic_loop.py (main)
  2399 strict = getattr(self._executor, "protected_effects_enabled", False)
  2401 self._fire_event("AGENTIC_TOOL_CALL_STARTED", ...
  2438-2465 work-pull ToolResultPresentation; 2466 await self._executor.invoke(; 2475 match_operation_handle
  2493-2545 _effect_handles; 2568 / 2586 ToolCallResult.from_tool_result; 2604-2605 strict re-raise
  2040-2041, 2079 zip(..., strict=True); 1217 class PresentedToolResult; 1282 inner_loop_hook; 1359 LoopTierSteps(
src/probos/cognitive/agentic_dispatch.py: 3755 AD-1129 _context.update; 3876 on_model_request_presented; 3879 loop = AgenticLoop(;
  3892 MCP_DISPATCH_OFFER_CONTEXT_KEY; 4111 tool_failures=correlate_tool_outcomes(
src/probos/cognitive/dm/reply_value.py:110  for call, res in zip(calls, results):
src/probos/cognitive/swe_harness/native_builder.py: 137 loop = AgenticLoop(; 157 agentic_result: AgenticResult = await loop.run(
src/probos/runtime.py: 645 self.registry = AgentRegistry(); 2717 self.identity_registry = infra.identity_registry
src/probos/startup/infrastructure.py: 60 strict profile; 117 await identity_registry.start(); 121-127 return InfrastructureResult(; 128 except BaseException:
src/probos/startup/results.py: 77 class InfrastructureResult; 84 effect_broker: ... = None
src/probos/startup/shutdown.py: 1311-1320 AD-824 cancel sweep; 1899-1902 _stop_pools_and_drain_intent_bus
src/probos/routers/agents.py: 1425 list_files; 1439 total_bytes; 1486, 1550, 1617, 1662 resolve_file; 1700-1702 dismiss
src/probos/tools/executor.py: 518 add_post_hook; 799 invoke; 911 match_operation_handle; 962 protected_effects_enabled
tests (AgenticLoop doubles and patch sites on main): test_ad1007:293/307, test_ad1142:389, test_ad1155:1507,
  test_ad1180:133, test_ad1189:352/955/2297, test_ad1190:835/2076/2083, test_ad1205:1969, test_ad1208:780,
  test_ad1209:263/283, test_ad1226:291/306, test_ad1228:1617/1630, test_ad1229:311/323, test_ad1229_e2e:135/147,
  test_ad1241:1532/2575/3259, test_ad1322:599/604, test_bf731:234/242
five R2-4 tests: test_ad1209:248; test_ad1226:354, 372; test_bf731:210, 221
scripts/gen_ad_ledger.py:20-31 (DECISIONS/PROGRESS require regeneration), 72-73 output paths
```

## Verified Against Codebase: addendum (2026-10-11, after Calls 3 and 4)

These were checked against the **staged** tree (index) of this worktree. Source edits were in progress in the working tree at the time and were not read.

```
git diff --cached refs/preserved/ordinary-1239-e38710b8 -- src/probos/security/file_access.py
  one hunk @@ -325,6 +325,11 @@ adding def is_reparse_point(...) -> bool, its docstring and return _is_reparse(info)  (the only deviation)
git show :src/probos/security/file_access.py | grep -n ...
  322 def _is_reparse   328 def is_reparse_point   504 def _leaf   556 flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
  602 def remove_file   612 def remove_directory
git show :src/probos/execution/workspace_result_store.py | grep -n ...
  136 return "transient"   137 return "integrity"   160 def _chain_intact   197 class DirectoryIdentities
  330 class GenerationReaper   416 if GENERATION_NAME_RE.fullmatch(name) is None:   427 if now >= generation_expiry(name):
  443 if tally.transient > transient_before:   452 if now >= generation_expiry(name) + RESULT_RETENTION_SECONDS:
  472 if is_reparse_point(info) or not (stat.S_ISREG(...) or stat.S_ISDIR(...)):
  517 intact = _chain_intact(parent)            <- replaced by the anchor check (F3)
  540 class ArtifactIO   604 committed_at = max(clock_value, generation_start(generation), self._high_water)
  605 if committed_at >= generation_start(generation) + GENERATION_SECONDS:
  620 artifact.publish_file("manifest.staged", "manifest.json")
  660 if clock_value >= generation_expiry(generation):   671 / 685 if clock_value >= reference.expires_at:
  699 class WorkspaceResultStore
  927 async def reap_tool_results(self, *, now: float | None = None)   928 pre-lock now check  <- removed (F1)
Read src/probos/execution/workspace_result_store.py (staged == working tree at read time)
  352-375 sweep(): root climb probe :358 and root pin/list :371-372 outside RetryRunner   <- F5
  377-410 _reap_owner(): namespace pin :382-384, list :387; transient branch WARNING :397   <- F5
  461-480 _reap_entry; 482-509 _reap_directory pins parent.path / name at :489   <- F3
  620-629 publish_file wrapped; :627 self._high_water = committed_at   <- F2 record point
  656-691 read(): reference from manifest :667, digest :679-683   <- F2 check point
  960-965 deferral log "publication stays enabled"   <- F7
Grep tests (staged): test_ad1240_workspace_result_lifecycle.py
  263 test_reap_refuses_a_now_ahead_of_the_store_clock (to delete, F1)   594 test_reaped_generation_identities_are_evicted (F6)
  1080 test_cap_deferral_and_foreign_entries_never_escalate   1207 test_integrity_failure_latches_publication
  2046 test_entry_refused_by_the_pinned_primitives_is_foreign_unless_the_chain_failed
  2087 test_enoent_on_the_leaf_is_success_but_enoent_in_the_chain_is_an_integrity_failure (retarget, F3-3)
  2128 test_posix_only_entry_names_the_primitives_refuse_are_left_in_place
Grep tests: test_ad1240_workspace_results.py:438 await store.reap_tool_results(now=clock)  (rewrite, F1)
.github/workflows/ci.yml:47 python-version: '3.12'
src/probos/startup/infrastructure.py:128 except BaseException:
```

**Not verified:**
- No test was run in Calls 3–5.
- POSIX behaviour (descriptor-relative removal, relocation, the symlink and FIFO cases, `is_reserved` on Python 3.12) is from reading only; it first runs on CI.
- That Windows anchor handles prevent renaming the namespace is inferred from the pins denying delete sharing, not executed.
- The figures inherited from the Builders and the reviewer were not reproduced: the 209 and 1019 resolve counts, the Windows timings (177 → 1021 ms and 162 → 889 ms), the reviewer's executed probes, and the 260 passed / 10 skipped run.
- The M2 code (round 2, the scandir walk) was not read; it was being reworked.

## Verified Against Codebase: addendum 2 (2026-10-11, after Call 6; written in Call 7)

These anchors were re-read in the **working tree**. M4a and M4b round 2 were landing at the time, so some lines below were in motion.

```
git rev-parse refs/preserved/ordinary-1239-e38710b8:tests/test_ad1191_delegation_wire.py
  c28c082fb947c73666752e69430d0d8b9b287f8d   (row 24, applied verbatim)
git rev-parse HEAD:tests/test_ad1191_delegation_wire.py 0ae79d95…:tests/test_ad1191_delegation_wire.py   (Call 6)
  1b1c25704b511b5941c38831974f1b4e458e33b9 (both)
src/probos/work_item_steps.py:29                      MAX_OWNED_VIEW_BYTES = 16 * 1024
src/probos/tools/work_item_steps_tool.py              20 class OwnedStepsViewResult(ToolResult); 142 return OwnedStepsViewResult(
                                                      166-167 _error returns ToolResult(   (C6-D1 already landing at read time)
src/probos/cognitive/swe_harness/result_offload.py    66 import OwnedStepsViewResult; 515 WorkPullReceipt branch (Call 6);
                                                      519 if type(raw) is OwnedStepsViewResult and raw.error is None:
src/probos/cognitive/agentic_dispatch.py              510 type(result) is not ToolResult (run_python only);
                                                      2829 elif tool_id == "read_owned_steps" and result.error is None:;
                                                      3904 if presentation.tool_name != "read_owned_steps":
src/probos/cognitive/swe_harness/agentic_loop.py      1712 iteration_ceiling = (; 1717 for iteration in range(1, iteration_ceiling + 1):;
                                                      2322 counted-iteration check; 2910-2911 DeliveryContext(delivery_run,
                                                      delivery_run.settings.max_iterations - iteration   <- C6-D2 replaces this
src/probos/execution/workspace_result_store.py        225-243 @dataclass(frozen=True) class _Committed with 7 fields incl. representation;
                                                      238 def of(cls, reference, owner_digest); 791 if recorded is not None and recorded != _Committed.of(reference, owner_digest):
src/probos/startup/infrastructure.py                  119 await trust_network.start(); 121 Sovereign Agent Identity block; 142 await identity_registry.start();
                                                      163 await workspace_store.start()   <- C6-D4.2 moves the store block before line 121
src/probos/startup/shutdown.py                        1907 with steps("pools stop and intent bus drain"):; 1916 await workspace_results.stop()
                                                      (no try/finally yet; C6-D4.1 adds it)
tests/test_ad1320_agentic_budget_awareness.py:615     blob pin 764d0f86… (unchanged; moved last in M5)
```

**Re-read for this addendum:** the lines listed above, plus Call 6's reads of `infrastructure.py:30–213`, `shutdown.py:1895–1924`, `agentic_loop.py:2780–2929`, `work_item_steps_tool.py` (whole file, before C6-D1) and `agentic_dispatch.py:2810–2849` and `:3800–3934`.

**Not re-read:**
- `_run_scoped`'s call sites for `_execute_tool_uses`;
- the M4a test file;
- the M4b lifecycle additions;
- `runtime.py` and `results.py` hunks;
- M2's scandir walk.

**Not verified:**
- No tests were run in Calls 6–7.
- The Builders' counts were not reproduced: 439/437/2, 206/12, 105 for ad1192, 41/43 mutants, and M4b's 19 mutants.
- The equivalent-mutant classifications were not checked.
- That the executor preserves a `ToolResult` subclass on the ordinary profile is inferred from the `WorkPullReceipt` armed-loop test.
- POSIX behaviour is from reading only.
- The whole-suite run that decides the C6-D5 file list had not reported.

## Absence Verified (2026-10-11)

```
CLAIM: main has no .tool-results / WorkspaceResults / bind_workspace_results yet (no persisted layout to migrate)
RUN:   Grep "tool-results|bind_workspace_results|WorkspaceResults" src/
FOUND: no matches
HOLDS: yes. The candidate never shipped, so no migration is needed.

CLAIM: main's work_item_pull_tool.py has no WorkPullReceipt
RUN:   Grep "WorkPullReceipt|class .*Receipt" src/probos/tools/work_item_pull_tool.py
FOUND: no matches
HOLDS: yes. Row 18 adds it verbatim.

CLAIM: there is no repo mutation script (the campaign is manual per §7)
RUN:   Glob scripts/*mutat*
FOUND: none
HOLDS: yes
```

---

## Prior Art and Blind Spots

All external sources are **search summaries, not fetched**.

| Idea | Source | Decision |
|---|---|---|
| Delete whole time-bounded blocks only when fully expired; `>=` at the boundary | [Prometheus storage docs](https://next.prometheus.io/docs/prometheus/2.55/storage/), [retention boundary fix #9633](https://forger.sitiv.fr/apitech/prometheus/commit/b7047f7fcb3fb35c6ebf349ac5b7a65973befcde), [TSDB retention write-up](https://ganeshvernekar.com/blog/prometheus-tsdb-compaction-and-retention/), all search summaries | **Adopt**: generation expiry = end of the hour + R |
| Age each entry by mtime or atime | [systemd-tmpfiles(8)](https://www.mankier.com/8/systemd-tmpfiles) (search summary); internal `tools/browser/recording_reaper.py:112` | **Reject**: an outsider can write mtime, and atime gets bumped. Use the name and the injected clock |
| Skip on `OSError` and retry next pass | `recording_reaper.py:130–133` (read) | **Adapt**: a bounded retry, then defer |
| Sharing violation, directory not empty and delete pending are transient | [Chromium delete_with_retry](https://gitcode.com/openharmony-tpc/chromium_src/blob/master/chrome/installer/mini_installer/delete_with_retry.cc), [SQLite](https://sqlite.org/src/info/89f1848d7f), PostgreSQL ([1](https://forger.sitiv.fr/open-dsi/postgres/commit/e109e43921d21d069c03f18d7c9d8f4e5cb6a0c3), [2](https://forger.sitiv.fr/open-dsi/postgres/commit/6d7547c21)), [Bazel](https://bazel.googlesource.com/bazel/+/e5a485c67fdef607ec0ae9ea37c5a166aac9c4df%5E%21/), all search summaries | **Adopt** winerror 32, 33, 5, 145 and 303 |
| Exponential wait up to about 1 s | [CPython `_waitfor`](https://remotebranch.eu/Stowage/cpython/commit/0158890005b0be9b6375fefabb2465eba2b6fd83), [bpo msg293428](https://bugs.python.org/msg293428), search summaries | **Adapt**: 0.75 s per operation, 2 s per sweep, injected sleep |
| POSIX delete semantics in DeleteFileW | [CPython #84324](https://github.com/python/cpython/issues/84324), [MS DDI](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddk/ns-ntddk-_file_disposition_information_ex), search summaries | **Do not depend on it**: it is undocumented, and the design holds either way |
| `shutil.rmtree` | [3.12 rmtree change](https://git.joshthomas.dev/mirrors/cpython/commit/02fbaf4887deaf0207a5805d3736e0124a694c14), [discussion](https://discuss.python.org/t/using-iterative-filesystem-walk-instead-of-recursive/21955/36), search summaries | **Reject**: use a bounded, pinned, depth-3 walk |
| Large-output offload: Copilot `largeToolResultsToDisk`; deepagents "pointer, not copy" | #1239 body | Already absorbed by the candidate |
| Internal research | `docs/research/` grep for retention, reaper and offload | Nothing applicable; only metaphors of cognitive offloading |

**Blind spots this contract closes:**
- N1 and N2: the method ceiling and the architecture checker. No prior review saw them.
- Three new loop doubles on main (AD1228, AD1229 ×2).
- The strict-profile interaction (N6).
- Owned-steps presentation acknowledgement (`agentic_dispatch.py:3856`).
- The unbounded directory-identity cache (N5).
- Volumes without hard links (FAT/exFAT), which fail as `workspace_write_failed` and are not lost.
- NFS silly-rename (`.nfsXXXX`) files, which defer.
- A backward clock and outsider-created future names (N4, and `high_water` is never restored).
- Tier-1 writers (C1).
- The golden fixture's premise moved (M0).
- **Cross-process safety (corrected in Call 10):** two ProbOS processes on one root are **not promised**. An artifact's margin against another process's clock is `end(G) − committed_at`, which is near zero for a commit late in its hour (§9). The earlier "R minus the publication time" bound was wrong. This is stated, not tested.

**Considered, deferred:** strict-profile offload; Tier-2 isolation (AD-995).

## Verified Against Codebase: addendum 3 (2026-10-12, after review round 3 repairs; written in Call 10)

Checked against the working tree, which equals the index (`git diff --stat`: empty). No test was run in Call 10.

```
git status --short / git diff --cached --name-only
  25 staged files: 23 code, test and fixture paths, docs/development/workspace-tool-results.md, this contract;
  tests/test_ad1320_agentic_budget_awareness.py not modified
Grep "AD-1240" tests/test_ad1125_room_bound_execution.py
  1316: # AD-1240 (#1239): the vector's size was incidental; armed delivery is tested in test_ad1240_*   (C6-D5 file)
wc -l (match the Builder reports)
  workspace.py 471; workspace_result_store.py 1170; workspace_results.py 453; result_offload.py 670; agentic_dispatch.py 4427
git ls-files -s (index blob ids; sha256 could not be computed under the bridge)
  agentic_dispatch.py 86be5f61f103; result_offload.py 1bce14f886c6; workspace.py 811871983f09;
  workspace_result_store.py b9ec26cf36a7; workspace_results.py 5a2e431c1338

agentic_dispatch.py (Grep)
  3513 _delivery_armed = plan_mode_tool_ids is None or "read_file" in plan_mode_tool_ids          grep -c -F: 1  (row 32)
  3514 _recovery_reader_full = _delivery_armed and not executor.protected_effects_enabled and not isinstance(...)
  3551 or (tid == "read_file" and _recovery_reader_full)                                             grep -c -F: 1  (row 28)
  3959 if _delivery_armed:   3963 logger.info("AD-1240: plan mode offers no recovery reader; this run keeps legacy delivery")
src/probos/cognitive/agent_mode.py:68-83 PLAN_MODE_TOOL_IDS: 14 ids, no "read_file"
result_offload.py (Grep, Read 294-400)
  316 if Path(path).is_absolute() and self.scope.workspace_promised(path):                         grep -c -F: 1  (row 30)
  324-333 promised_workspace recorded inside the try; 334 except Exception: ... return None
  342 if promised_workspace:  (after the try)                                                       grep -c -F: 1
  368 async def _promised_context(self, tool_id, path, directive: RecoverRead | None)
  379 directive is None and tool_id != "read_file" -> reader_unavailable; 385 admitted_reader.matches(reader)
  391 if target != Path(path): raise WorkspaceResultError("source_changed")                      grep -c -F: 1  (row 31; line 392 and `import os` added in review round 4: `Path(os.path.normpath(path))`)
  604 context.run.scope.reserve_workspace(reference)                                               grep -c -F: 1  (row 29)
  DeliveryRun defs 247-423: 10
workspace_results.py SourceRecoveryScope (Read 217-291)
  defs: __init__, _key, select, reserve, reserve_workspace (258), workspace_promised (264), validate, close = 8
  227 self._workspace: set[str] = set(); 291 close() clears it
workspace_result_store.py (Grep, Read 392-736, 998-1169)
  43 from functools import partial; 80 SWEEP_ENTRY_CAP = 10_000; 216 def knows
  392 def _rotated (module level); 405 def _is_expired (module level); 412 / 423 the row 3 / row 1 lines
  GenerationReaper defs 449-729: 15 (__init__, sweep, _pin, _probe, _listed, _note_cap, _reap_root, _hold,
    _reap_owner, _reap_namespace, _reap_expired, _reap_entry, _reap_directory, _settle, _integrity_failure)
  467 self._capped_at: dict[Path, str] = {}
  511 self._identities.remember(runner.run(partial(self._probe, existing), _transient))             grep -c -F: 1  (row 21)
  514 if existing == self._root and self._identities.knows(self._root):                              grep -n: one line (row 37)
  528 / 588 identities, names = runner.run(partial(self._listed, <root|namespace>), _transient)     one line each (rows 42 / 41)
  532 / 595 for key|name in _rotated(names, self._capped_at.get(...)):                                one line each (rows 40 / 39)
  590 if self._identities.knows(namespace):                                                           grep -n: one line (row 38)
  614 evict_under at the start; 615 deferred_before = tally.deferred                                 grep -n: one line (row 35)
  617-621 success branch: self._committed.evict_generation(namespace, name)                           grep -n: one line (row 36)
  712-727 _settle: chain first; FileAccessDenied/ValueError -> skipped; any other non-gone, non-transient -> _integrity_failure
  latch sites: 1022-1023 / 1035-1036 start() failure or cancellation; 1071-1075 reaper task cancelled or raising;
    1139-1147 sweep cancelled or raising; 1155-1156 result.failed
workspace.py (Read 190-305, Grep 441-468)
  209 info = os.lstat(directory)  # no-follow ...                                                  grep -c -F: 1  (row 33)
  210 S_ISDIR and not is_reparse_point and identity == expected; 221 / 225 checked before and after the scan
  239 if entry.name.casefold() == RESULT_DIRECTORY:  # the reserved name, in any case               grep -c -F: 1  (row 23)
  263 if not child.link and not child.is_dir:                                                         grep -c -F: 1  (row 22)
  269-273 a kept link is sized from checked.stat(); 274 opaque = child.is_dir and not child.link and ... grep -c -F: 1  (row 34)
  302 enter = entry.is_dir and not child.link and ...; 444 a non-opaque directory (a directory link included) has size 0
  WorkspaceManager defs 311-453: 9
agentic_loop.py AgenticLoop defs 1373-2982: 13
tests (Grep "def test_")
  delivery: 4920, 4928, 4936, 4995, 5034 (loss list at 5032 includes resolver_answers_differently), 5133, 5172, 5223,
    5292, 5327, 5357
  lifecycle: 2671, 2934, 3109, 3150, 3195, 3233, 3265, 3304, 3337, 3400, 3434, 3456
  results: 715, 768, 1086, 1139, 1514, 1540, 1644, 1651, 1680, 1726, 1819
```

**Not verified in Call 10:**
- The Builder-reported sha256 prefixes and all mutation verdicts (no command that computes sha256 or runs tests is allowed under the bridge); line counts match the reports.
- The orchestrator's figures: two cached identities per generation, 15 POSIX-skipped cases in 8 functions at M5a, the 16.8 KB rendered page, the 744-byte entry, the 15–17 s lock hold.
- Linux behaviour of any POSIX-premise test.
