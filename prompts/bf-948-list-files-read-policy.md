# BF-948 (#1736): list_files lists only what the read policy admits

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-03
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-04, before the build: the two tracker heads of section 8 carry 2026-11-04, the local date of M3's commit, as section 8's Date rule requires; and the base of this build is `ca0ca20b` (BF-949's merge), which changes none of the files this contract touches (`git diff --stat 317fcdc0 ca0ca20b -- src/probos/cognitive/swe_harness/tools.py src/probos/tools/effect_tiers.py src/probos/security/file_access.py tests/test_ad1316_real_effect_routes.py` is empty).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-04, Amendment 1 after review round 1 (`logs/bf948/review-r1-report.md`): F2 becomes M4 (a refusal the policy decided is not a tool fault, and `read_file` answers "refused" only for the policy's refusal); F3 corrects two claims (§3 LF2, §12, §16 item 1). F1 is BF-953, its own bug and contract, built before M4 in this PR; it changes `security/file_access.py`, which BF-948 still does not touch. M4's line numbers are those of `9649df65`.
**Status:** M1 to M3 built (`b70d8b14`, `60177ff7`, `5517cd34`). M4 to build after BF-953, in the same PR; round 2 reviews the whole candidate. **Base:** drafted on `317fcdc0` (tree `4ca36294`); M4 drafted on `9649df65`. **Dependencies:** BF-953 is built first (its own contract). **Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD, M4 HIGH. **Estimated tests:** 1 new file, `tests/test_bf948_list_files_read_policy.py` (12 test functions, 30 cases after M4); M2 edits `tests/test_ad1316_real_effect_routes.py`.
**BF number:** BF-948, held by the title of #1736 (`gh issue view 1736`: OPEN). `git log --all -i --grep BF-948` finds `2d925bf5` (AD-1356 S2's repair), which mentions it and does not fix it. Nothing allocated.
**Priority:** the next queue item after BF-949. Low to medium: names and an existence oracle, never contents. Any crew agent holding the native SWE tools can reach it once an operator sets `security_infra.read_roots`.

**Which text describes the head.** §1 to §3 describe `317fcdc0`, and the line numbers are that commit's. Before building, run `git diff --stat 317fcdc0 HEAD -- src/probos/cognitive/swe_harness/tools.py src/probos/tools/effect_tiers.py src/probos/security/file_access.py tests/test_ad1316_real_effect_routes.py`. A SEARCH that no longer matches goes back to the Architect; it is not rebased by hand. P2-5 to P2-14 quote N1-1. Where prose differs from a REPLACE or new-file block, the block wins. "Head text" means every docstring, comment, log message, error string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

1. **The tool skips the policy.** `ListFilesTool.invoke` (`cognitive/swe_harness/tools.py:531-565`):
   - It resolves `path` with `_resolve_path` (`:245-248`). An absolute path passes through unchanged. A relative one is rooted at `_PROJECT_ROOT`, the checkout's `src/` (`:79`, `parents[3]`).
   - It then returns `[str(p.relative_to(_PROJECT_ROOT)) for p in base.glob(pattern)]` (`:543`).
   - It never calls `resolve_for_runtime` or `resolve_read_path` (`security/file_access.py:401-411`, `:105-162`). `ReadFileTool` calls the first at `:448`, and so does `CodebaseReadSourceTool` at `:754`.
   - So `security_infra.read_roots`, the floor (the data directory and the config files, `:151-158`) and the credential file names (`:148-149`) never apply to it.
2. **Three leaks.**
   - A match outside `src/` makes `relative_to` raise. The reply is `list_files failed: <the ValueError text>`, which names the match's absolute path (`:563`), and the same text is logged at WARNING (`:551`, `:556`).
   - Inside a strict effect dispatch (`_effect_dispatch_context`, set by `tools/executor.py:861-867`) the reply is the bounded `list_files_failed`, and only the exception class is logged.
   - A pattern that climbs with `..` returns names above `src/` in the success output.
3. **A permitted root outside `src/` cannot be listed at all**: every match raises in `relative_to`.
4. **Reach.** The tool is registered with `read_perms` for all four ranks (`:1380-1385`, `:1400`). AD-1356 S2 keeps it in the elevated tier because of this gap (`tools/effect_tiers.py:40-45`).
5. **Measured on `317fcdc0`** with the orchestrator's probe: real `ReadFileTool` and `ListFilesTool` over a stub runtime carrying `read_roots` (`logs/bf948/probe-evidence-head-317fcdc0.txt`, gitignored).
   - Premise held: `read_file` refuses `outside/secret-name-1.txt` with "outside every readable root", reads `allowed/ok.txt`, and refuses a `..` spelling.
   - `list_files("*", <outside dir>)` gave `list_files failed: '<…\outside\secret-name-1.txt>' is not in the subpath of '<…\src>'`.
   - `list_files("*", <allowed dir>)` failed the same way.
   - `list_files("../*", ".")` returned 44 names above `src/`.
   - In a strict context the reply was `list_files_failed`.
6. **Found in review round 1 (F2), on `9649df65`: M2's refusals are tool faults to the fault detectors.**
   - `is_caller_input_error` (`tools/protocol.py:100-106`) recognises only `<id>_invalid:`.
   - `classify_tool_error` (`tools/executor.py:350-363`) finds no signature in `list_files refused: path is outside every readable root`. The result is `other`, which is not in `_NOISE` (`fault_detection.py:32-35`).
   - `detect_tool_defect` (`fault_report.py:392-416`) never consults the classifier. It feeds the same-run lane (`fault_detection.py:266`) and the DM filer (`agentic_dispatch.py:4376`).
   - So two identical refusals in one run are a `ToolDefect`, and the observer persists an open fault for `list_files` (measured by the reviewer with the production detectors and a real `FaultReportStore`).
   - `read_file refused:` has the same shape on the base. And `read_file` answers *any* resolver exception that way: `tools.py:463-467` catches `Exception`, not `FileAccessDenied`.

## 2. Solution

- **M1:** a real-tool test file, written first. Every case that changes is `xfail(strict=True)` and fails on the base; the compatibility case passes on the base.
- **M2:** `ListFilesTool.invoke`:
  - refuses a pattern that is not an exact str, is anchored, or has a `..` part;
  - composes the policy's roots once, then resolves the base through `resolve_read_path` with exactly the roots `resolve_for_runtime` uses, and refuses it with the policy's reason;
  - resolves every match and lists it only if the same policy admits it;
  - lists a match under `_PROJECT_ROOT` relative to it, and any other by its absolute path;
  - answers and logs a failure with its exception class only.

  The false sentence about `list_files` in `effect_tiers.py` is corrected, and the AD-1316 strict-log test is rewritten for the new seam.
- **M3:** trackers and the ledger.
- **M4 (Amendment 1):** a refusal the policy decided is not a tool fault.
  - `tools/protocol.py` adds `POLICY_REFUSAL_MARK` (`" refused: "` after the tool's own id) to `is_caller_input_error`, which both detectors already consult.
  - `ReadFileTool.invoke` answers `read_file refused:` only for a `FileAccessDenied`. Any other resolver error goes to its failure path and still counts.
  - Tests T10 to T12, and the tracker entries are amended.

## 3. Decisions

Criteria order: correctness, safety, compatibility, architectural fit, reversibility, validation cost.

- **LF1, the base (D1). Chosen (b): compose the three root lists once per call and decide the base with `resolve_read_path(str(path), …, relative_base=_PROJECT_ROOT)`.**
  - This is `resolve_for_runtime` by construction (`file_access.py:401-411` is exactly that composition), so the base is decided as `read_file` decides its path.
  - One composition means the base and every match are judged against the same roots. A runtime change mid-call cannot split the decisions.
  - It is the pattern `tools.py:337-341` and `:910-915` already use inline, and that `agents/code_search.py:323-359` (`_ReadFloor`) uses.
  - A refused base answers `list_files refused: <the policy's reason>` (the same form as `read_file refused:` at `:466`), lists nothing and logs nothing.
  - `str(FileAccessDenied)` is the reason alone (`file_access.py:82-85`). The reasons:
    - "outside every readable root" (the roots);
    - "path is protected: the runtime's data directory or a config file" (the floor; the workspace exemption, `:152-158`, still applies);
    - "that file holds credentials and is not readable" (the name rule);
    - "empty or malformed path";
    - "path could not be resolved: <OS text>" (L4).
  - The base check is path-based, not existence-based (`resolve()` is not strict), so a refusal is identical for a path that exists and one that does not (T2).
  - Rejected:
    - (a) `resolve_for_runtime` for the base plus a fresh `resolve_for_runtime` per match. The roots are rebuilt per match; BF-908's review measured 200 matches costing 200 floors (`code_search.py:326-330`).
    - (c) Reusing `code_search._ReadFloor`. It is private to `agents/`, so `cognitive` would import an `agents` private; promoting it is a shared-contract change in a security module. Considered, deferred: a public per-call `ReadPolicy` in `file_access.py`, as a DRY follow-up.
- **LF2, the pattern and the matches (D2). Chosen (a): a lexical pattern rule, then a per-match policy decision; refused matches are dropped silently.**
  - **What `Path.glob` does.** On CPython 3.12 (`Lib/pathlib.py`) and 3.13 (`Lib/pathlib/_local.py`), an anchored pattern raises `NotImplementedError("Non-relative patterns are unsupported")`. On 3.12, `..` is a `_ParentSelector` (the probe's 44 names), a non-directory base selects nothing, and `**` walks with `follow_symlinks=False`. CI runs 3.12 on Ubuntu (`.github/workflows/ci.yml:17`, `:47`).
  - **The tool's own rule.** It does not rely on that behaviour. It refuses `type(pattern) is not str`, `Path(pattern).anchor` (a drive, a root or a UNC share on Windows; `/` on POSIX), and `".." in Path(pattern).parts`, with a fixed text that names nothing. The check uses the platform's flavour, which is the one `glob` parses with.
  - **The authority is the per-match check.** Each match is decided by `resolve_read_path(str(match), …)` (resolve, then containment, `file_access.py:130-162`). That catches a symlink or junction, a Windows case or 8.3 spelling (`resolve()` canonicalises an existing path), and any spelling the lexical rule misses (L1).
  - **The reply for dropped matches.** Nothing: no name, no count. A count would itself be an existence oracle. The reply lists exactly what the read policy admits. That is not a promise that every entry is readable: a directory entry is listed on purpose (T3), and `read_file` of a directory fails.
  - **The reply form.** A kept match under `_PROJECT_ROOT` is relative to it, as before. Any other is its absolute path, which `read_file` accepts as given (T3 reads one back).
  - Rejected:
    - (b) Allow `..` patterns and rely on the per-match check alone. It is correct and more compatible, but it makes the base check meaningless: the pattern then navigates. Safety ranks above compatibility.
    - (c) Drop and report a withheld count: an oracle.
    - (d) Refuse the whole call if any match is refused. It is a one-bit oracle, and a listing of the checkout would always fail on `config/system.yaml`.
    - Reply form relative to the base: it cannot be fed to `read_file`, and it changes the in-tree form.
    - Reply form always absolute: it changes the in-tree form for no gain.
- **LF3, the reply and the log (D3).**
  - A pattern refusal or a base refusal is an answer, not a failure: same reply in both contexts, and no log line.
  - Any other exception:
    - In a strict dispatch, the reply stays `list_files_failed` and the strict log line keeps its text, with `type(exc).__name__`.
    - Otherwise, the reply is `list_files failed: <ExceptionClass>`, and the log line carries `pattern=%r path=%r error_type=%s`: the caller's own input and the class, never the exception's text. `%r` neutralises line breaks.
  - A dropped match is never logged.
  - Rejected: keeping `{exc}` in the non-strict reply (it is the defect); a bounded `list_files_failed` everywhere (it loses the class, which the strict path already shows the broker).
- **LF4, the tier (D4). Chosen (a): `effect_tiers.py`'s sets are unchanged in BF-948.**
  - Its comment says `list_files` "resolves its path without the read policy" (`:41-42`), which M2 makes false. So P2-3 deletes that clause and records the hold.
  - (b), moving `list_files` into `ROUTINE_TOOL_IDS ∩ READ_POLICY_TOOL_IDS` in this fix, is rejected. When `read_roots` is set it lowers who decides a call: routine is `auto` by default, where elevated is `chief`. That weakens an authorization control, a Captain condition. It also changes the product objective beyond a security fix and rewrites ET1, ET3 and S3's CC tests.
  - (c), a follow-up table change after the Captain's yes, is the route for that change.
  - Not a Captain condition for BF-948: option (a) is viable and weakens nothing. The Captain decision it leaves is in §12.
- **LF5, the class (D5).** Enumerated by Absence A1 and A2 (commands, not recall).

  | Reader | How it reaches a path | Status |
  |---|---|---|
  | `read_file` (`tools.py:446-448`) | `resolve_for_runtime` | covered |
  | `codebase_read_source` (`:752-754`) | `resolve_for_runtime` | covered |
  | `standing_orders_lookup` (`:899-915`) | a name, then `read_verified_file` with the roots | covered (BF-910) |
  | `list_files` (`:508-565`) | `_resolve_path` + `glob` | **fixed here** |
  | `codebase_query` / `_find_callers` / `_find_tests` / `_get_imports` | `CodebaseIndex` | not traced here; F-202 (#1523) records that the indexed source readers have no shared floor |
  | `write_file`, `edit_file`, `run_command` | the write floor; the shell | not readers of this kind; out |
  | `FileReaderAgent` (`agents/file_reader.py:106-108`) | `resolve_for_runtime` with `_runtime` None from the pool | BF-944 (#1717) |
  | `DirectoryListAgent` (`agents/directory_list.py:107-133`) | the base through the policy; `iterdir` entries, `entry.stat()` follows a link | BF-944. **Add to BF-944's acceptance:** an entry that is a link out of the roots (its target's size is reported) |
  | `FileSearchAgent` (`agents/file_search.py:128-147`) | the base through the policy; `p.rglob(pattern)` with the caller's pattern, matches never re-checked | BF-944. **Add to BF-944's acceptance:** a pattern with `..` or a link out of the roots lists nothing outside them. BF-944's own acceptance ("a search … outside them … is refused") already requires it |
  | `CodeSearchAgent` (`agents/code_search.py:143-166`, `:323-379`) | the base, then a per-file `_ReadFloor` | covered (BF-908) |
  | `copilot_adapter` standing orders (`:105-113`) | `read_verified_file` with the roots | covered |
  | `copilot_adapter.py:800`, `tools/use_skill_tool.py:184`, `tools/code_execution_tool.py:1198`, `tools/browser/*` | their own directories, no caller path | n/a |

  The two `agents/` cases are not fixed here: another module, inert until BF-944 hands those pools a runtime, and the slice stays at one module. The orchestrator records them on #1717.
- **LF6, the tests (D6).**
  - The real `ListFilesTool` and `ReadFileTool` over a stub runtime carrying exactly what the policy reads (T1 to T8).
  - One agent-work run end to end on the AD-1347 rig (`tests/test_ad1347_s3_execution.py` `_rig`: the real `ToolRegistry`, `AgentWorkRunner` and `WorkItemAgenticExecutor`), with the native tools registered by `register_native_swe_tools` through `tests/test_ad1356_s2_tool_effect_table.py` `_native` and elevated calls decided `auto` (`tests/test_ad1356_s3_chain_of_command.py` `_chain`, as in S4's WD1): T9.
  - Rewritten, not deleted: `test_strict_list_files_logging_omits_raw_arguments` (`test_ad1316_real_effect_routes.py:1478-1495`) monkeypatches `tools._resolve_path`, which `list_files` no longer calls. P2-4 moves the patch to `tools.resolve_read_path`, and its assertions are unchanged.
  - Unchanged, and recorded: S4's WD1 (`test_ad1356_s4_who_decides.py:41-53`) and S3's `_seen(rig, "notes.txt")` assertions (`test_ad1356_s3_chain_of_command.py:150`, `:181`, `:283`) pass on the base **only through the defect's error text**, which names `notes.txt`. After M2 they pass through a successful listing whose absolute path contains it. T9 is the test that tells the two apart.
- **LF7, the refusal is not a fault (D7, Amendment 1). Chosen (a): a second own-id mark in `is_caller_input_error`, and `read_file`'s refusal narrowed to the policy's refusal.**
  - **What the count protects.** A fault report says a tool is broken. A refusal is the tool working: the policy decided, and the reply says why. Counting it files a fault the repair path cannot fix, and it hides nothing a fault report should carry.
  - **The mark.** `POLICY_REFUSAL_MARK = " refused: "`. A result is marked when its error starts with the tool's own non-empty id, then the mark, then at least one more character (case-sensitive). This is the same rule as S1.2's `_invalid:` mark, applied in the same function.
    - So `fault_report.py:401` and `fault_detection.py:296` are unchanged, and a marked refusal is neither fault nor success evidence on both lanes.
    - `list_files` gives the mark for a `FileAccessDenied` (`tools.py:571-572`) and for its pattern rule (`:511`). `read_file` gives it only for a `FileAccessDenied`.
  - **The narrowing.** `ReadFileTool.invoke` re-raises a resolver exception that is not a `FileAccessDenied`. It then reaches the existing outer handlers: `File not found: …` or `read_file failed: <exc>` (`tools.py:492-506`), and it still counts.
    - `isinstance` is used so a future subclass stays a refusal.
    - The `RecoverRead` branch is unchanged.
    - This is the shape `codebase_read_source` already uses (`:805-808`).
  - Rejected:
    - (b) A separate `is_policy_refusal` called at both sites. It edits two lines AD-1356 S1's RX-6 and RX-7 pin verbatim, and it leaves a third consumer to drift. The two marks mean the same thing to every consumer.
    - (c) Adding the refusal texts to `classify_tool_fault_error`. That is insufficient: `detect_tool_defect` (the same-run lane and the DM filer) never consults the classifier, and the reasons are dynamic texts.
    - (d) Answering `list_files_invalid:<code>`. That loses the policy's reason, which the model needs, and breaks parity with `read_file refused:` (LF1).
    - (e) Answering a refusal as a success. The model and `ToolResult.success` would read it as a listing.
    - (f) Widening the mark without the narrowing. A defect in the policy layer would be answered "refused" and would stop being reported.
  - Not a Captain condition: the read policy enforces exactly as before. Only its own answers stop counting as tool defects.
- **Config:** none. **EventType:** none. **No class and no method** is added; M4 adds one module constant, `POLICY_REFUSAL_MARK`. `file_access.py` is unchanged by BF-948 (BF-953 changes it). The tool's id, name, description, input schema and output schema are unchanged; two goldens pin the description (A5).

## 4. Milestones and gates

| M | Tier | Why | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only, no `src`. Its strength is held by the strict xfails failing on the base, the premise asserts, and §10 | N1-1 | G1 |
| M2 | HIGH | an agent-reachable read path's admission decision (the security control itself), its reply and log text, and a sentence in the approval-tier table | P2-1 to P2-14 | G2 |
| M3 | STANDARD | trackers | P3-1, P3-2, the ledger | G3 |
| M4 | HIGH | a shared predicate consumed by both fault-detection lanes, the DM filer and a replay script, and `read_file`'s reply on an agent-reachable read path | P4-1 to P4-7, the ledger | G4 |

- **G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf948_list_files_read_policy.py -q -n 0`. Expected: 1 passed (T7), 16 xfailed.
- **G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf948_list_files_read_policy.py tests/test_ad1316_real_effect_routes.py tests/test_ad544_native_tools.py tests/test_ad1179_tool_schema_golden.py tests/test_ad1152_agentic_correlation.py tests/test_ad1356_s2_tool_effect_table.py tests/test_ad1356_s3_chain_of_command.py tests/test_ad1356_s4_who_decides.py tests/test_bf758_file_read_confinement.py tests/test_ad1344_constitution_write_refusal.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`. Expected in the new file: 17 passed.
- **G3:**
  - `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
  - `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
  - `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`
- **G4, red first.**
  - Apply P4-3 to P4-5 only (the test file), then run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf948_list_files_read_policy.py -q -n 0`.
  - Expected on the BF-953 head: **5 failed, 25 passed**. The five are T10 `list-files-refusal`, `pattern-refusal` and `read-file-refusal`; T11 on `faults.list_open() == [] and events == []`; and T12 on `broken.error`.
  - Any other count, or a failure on a line marked `# premise`, is a hard stop back to the Architect. If BF-953 added tests to this file, add its count.
- **G4, green.**
  - Apply P4-1 and P4-2, then rerun the file. Expected: **30 passed**.
  - Then run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf948_list_files_read_policy.py tests/test_ad1356_s1_input_errors.py tests/test_ad1356_replay_approval_tiers.py tests/test_ad1205_fault_observer.py tests/test_ad1205_fault_paths.py tests/test_ad1169_fault_reports.py tests/test_ad1257_defect_follows_failure.py tests/test_ad1279_fault_finds_its_trace.py tests/test_ad1164_continue_or_ask.py tests/test_ad1189_deferred_tool_schemas.py tests/test_ad1156_plan_execute_mode.py tests/test_ad1240_tool_result_delivery.py tests/test_bf758_file_read_confinement.py tests/test_ad544_native_tools.py -q -n 0`. Expected: 0 failed; record each file's count.
  - Then run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`.
  - After P4-6 and P4-7, run G3's three ledger commands.

**Order in the PR.**
1. M1 to M3 (committed).
2. BF-953: its own contract and commits, built first.
3. The orchestrator commits this amended contract.
4. M4.

F3 is text in this contract only. If BF-953 changed `tools.py:460-467` or the tail of this test file, so that a P4 SEARCH no longer matches, it goes back to the Architect and is not rebased by hand. The broad gate runs once for the whole batch, after round 2's repairs.

The broad gate runs once for the batch (main session, `--receipt`).

## 5. Commit messages

- M1: `BF-948 M1: real-tool reproductions of list_files outside the read policy`
- M2: `BF-948 M2: list_files lists only what the read policy admits, and names nothing it refuses`
- M3: `BF-948 M3: trackers and ledger`
- M4: `BF-948 M4: a refusal the read policy decided is not a tool fault, and read_file says refused only for the policy's refusal`

## 6. Tests (`tests/test_bf948_list_files_read_policy.py`)

| Id | Test | Covers | xfail until |
|---|---|---|---|
| T1 | `test_list_files_refuses_a_base_outside_every_readable_root` (3 spellings × plain/strict) | LF1, LF3; acceptance 1 | M2 |
| T2 | `test_a_refusal_is_the_same_whether_the_path_exists` | LF1: no existence oracle | M2 |
| T3 | `test_list_files_lists_a_permitted_root_outside_the_project_tree` | LF2 reply form; the result feeds `read_file` | M2 |
| T4 | `test_a_pattern_that_climbs_or_is_anchored_is_refused` (4) | LF2 pattern rule | M2 |
| T5 | `test_a_link_inside_a_permitted_root_to_outside_is_not_listed` | LF2 per-match check | M2 |
| T6 | `test_the_floor_and_credential_names_are_dropped_with_no_read_roots` | acceptance 2 (floor, names, workspace exemption) | M2 |
| T7 | `test_in_tree_listing_is_unchanged` | compatibility | none |
| T8 | `test_a_failure_reply_and_log_name_no_path` | LF3 | M2 |
| T9 | `test_an_agent_work_run_lists_inside_the_roots_and_is_refused_outside_them` | LF6 whole path | M2 |
| T10 | `test_a_tools_own_refusal_mark_is_not_a_tool_fault` (11) | LF7 the mark; S1.2's mark unchanged | red first in G4 (no xfail) |
| T11 | `test_repeated_refusals_in_an_agent_work_run_file_no_fault` | LF7 whole path: real tools, real executor, both detectors, a real `FaultReportStore` | red first in G4 |
| T12 | `test_read_file_answers_refused_only_for_the_policys_refusal` | LF7 narrowing; a resolver failure still counts beside two skipped refusals | red first in G4 |

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_bf948_list_files_read_policy.py` (new)

```python
"""BF-948 (#1736): list_files lists only what the read policy admits.

The real ``ListFilesTool`` and ``ReadFileTool`` over a runtime carrying what the read policy reads
(``config.security_infra.read_roots``, ``config.execution.workspace_root`` and ``data_dir``), and one
agent-work run on the AD-1347 rig with the native tools registered. Nothing here replaces the read
policy except T8, which makes it raise to reach the failure handler.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import requests_for_work_item
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _rig, _seen
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _chain, _finished

SECRET_NAME = "secret-name-948.txt"
_OUTSIDE = "list_files refused: path is outside every readable root"
_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file"
_PATTERN_REFUSAL = (
    "list_files refused: pattern must be a relative glob with no '..' part; name the directory in path"
)
_M2 = "BF-948 M2: on the base list_files never asks the read policy"


@dataclass(frozen=True)
class _Scene:
    root: Path
    allowed: Path
    outside: Path
    data: Path
    workspace: Path


def _scene(tmp_path: Path) -> _Scene:
    """``allowed/`` (ok.txt, sub/inner.txt), ``outside/`` (the secret name), ``data/`` with the agent
    workspace under it, and a credential vault file name at the root."""
    root = tmp_path.resolve()
    allowed, outside, data = root / "allowed", root / "outside", root / "data"
    workspace = data / "workspaces"
    (allowed / "sub").mkdir(parents=True)
    outside.mkdir()
    workspace.mkdir(parents=True)
    (allowed / "ok.txt").write_text("ok", encoding="utf-8")
    (allowed / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    (workspace / "scratch.txt").write_text("scratch", encoding="utf-8")
    (root / "credential_vault.json").write_text("{}", encoding="utf-8")
    return _Scene(root, allowed, outside, data, workspace)


def _runtime(scene: _Scene, *, read_roots: list[Path]) -> SimpleNamespace:
    """What the read policy reads: the roots, the workspace root and the data directory (the floor)."""
    return SimpleNamespace(
        data_dir=scene.data,
        config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[str(root) for root in read_roots]),
            execution=SimpleNamespace(workspace_root=str(scene.workspace)),
        ),
    )


async def _list(
    scene: _Scene, read_roots: list[Path], pattern: Any, path: str | None = None,
    context: dict[str, Any] | None = None,
) -> Any:
    params = {"pattern": pattern} if path is None else {"pattern": pattern, "path": path}
    return await ListFilesTool(_runtime(scene, read_roots=read_roots)).invoke(params, context)


def _link(link: Path, target: Path) -> None:
    """A directory junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _unlink(link: Path) -> None:
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.parametrize("strict", [pytest.param(False, id="plain"), pytest.param(True, id="strict-dispatch")])
@pytest.mark.parametrize("spelling", ["absolute", "dotdot", "other-case"])
async def test_list_files_refuses_a_base_outside_every_readable_root(
    tmp_path: Path, spelling: str, strict: bool,
) -> None:
    """``read_file`` refuses a file in that directory, so the roots are live; ``list_files`` refuses the
    directory with the policy's reason, in a strict effect dispatch too, and names nothing in it."""
    scene = _scene(tmp_path)
    runtime = _runtime(scene, read_roots=[scene.allowed])
    refused = await ReadFileTool(runtime).invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise
    path = {
        "absolute": str(scene.outside),
        "dotdot": str(scene.allowed / ".." / "outside"),
        "other-case": str(scene.outside).swapcase(),
    }[spelling]
    context = {"_effect_dispatch_context": object()} if strict else None
    result = await ListFilesTool(runtime).invoke({"pattern": "*", "path": path}, context)
    assert result.error == _OUTSIDE and result.output is None


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_refusal_is_the_same_whether_the_path_exists(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    present = await _list(scene, [scene.allowed], "*", str(scene.outside))
    absent = await _list(scene, [scene.allowed], "*", str(scene.outside / "no-such-dir"))
    assert present.error == absent.error == _OUTSIDE


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_list_files_lists_a_permitted_root_outside_the_project_tree(tmp_path: Path) -> None:
    """A match outside the project tree is listed by its absolute path, which ``read_file`` accepts as given."""
    scene = _scene(tmp_path)
    top = await _list(scene, [scene.allowed], "*", str(scene.allowed))
    assert top.error is None
    assert set(top.output["files"]) == {str(scene.allowed / "ok.txt"), str(scene.allowed / "sub")}
    deep = await _list(scene, [scene.allowed], "**/*.txt", str(scene.allowed))
    assert set(deep.output["files"]) == {
        str(scene.allowed / "ok.txt"), str(scene.allowed / "sub" / "inner.txt"),
    }
    read = await ReadFileTool(_runtime(scene, read_roots=[scene.allowed])).invoke(
        {"path": deep.output["files"][0]},
    )
    assert read.error is None


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.parametrize("pattern", [
    pytest.param("../*", id="climbs"),
    pytest.param("sub/../../*", id="climbs-after-a-step"),
    pytest.param("{anchor}*", id="anchored"),
    pytest.param(["*"], id="not-a-string"),
])
async def test_a_pattern_that_climbs_or_is_anchored_is_refused(tmp_path: Path, pattern: Any) -> None:
    """Reads are unconfined here and the base is the project tree, so only the pattern rule refuses."""
    scene = _scene(tmp_path)
    if pattern == "{anchor}*":
        pattern = scene.root.anchor + "*"
    result = await _list(scene, [], pattern)
    assert result.error == _PATTERN_REFUSAL and result.output is None


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_link_inside_a_permitted_root_to_outside_is_not_listed(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    door = scene.allowed / "door"
    _link(door, scene.outside)
    try:
        assert (door / SECRET_NAME).is_file()  # premise: the link reaches the outside file
        runtime = _runtime(scene, read_roots=[scene.allowed])
        refused = await ReadFileTool(runtime).invoke({"path": str(door / SECRET_NAME)})
        assert refused.error == "read_file refused: path is outside every readable root"  # premise
        lister = ListFilesTool(runtime)
        top = await lister.invoke({"pattern": "*", "path": str(scene.allowed)})
        assert top.error is None
        assert set(top.output["files"]) == {str(scene.allowed / "ok.txt"), str(scene.allowed / "sub")}
        through = await lister.invoke({"pattern": "door/*", "path": str(scene.allowed)})
        assert through.output == {"files": []}
        everything = await lister.invoke({"pattern": "**/*", "path": str(scene.allowed)})
        assert everything.error is None and "secret-name-948" not in repr(everything.output)
        assert str(door) not in everything.output["files"]
    finally:
        _unlink(door)


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_the_floor_and_credential_names_are_dropped_with_no_read_roots(tmp_path: Path) -> None:
    """Reads unconfined: the data directory and a credential vault file name are not listed, the data
    directory is refused as a base, and the agent workspace under it is listed."""
    scene = _scene(tmp_path)
    top = await _list(scene, [], "*", str(scene.root))
    assert top.error is None and set(top.output["files"]) == {str(scene.allowed), str(scene.outside)}
    assert (await _list(scene, [], "*", str(scene.data))).error == _PROTECTED
    work = await _list(scene, [], "*", str(scene.workspace))
    assert work.output == {"files": [str(scene.workspace / "scratch.txt")]}


async def test_in_tree_listing_is_unchanged(tmp_path: Path) -> None:
    """A match under the project tree (the checkout's ``src``) is listed relative to it, as before BF-948."""
    scene = _scene(tmp_path)
    nested = await _list(scene, [], "*.py", "probos/cognitive/swe_harness")
    assert str(Path("probos", "cognitive", "swe_harness", "tools.py")) in nested.output["files"]
    default = await _list(scene, [], "probos/__init__.py")
    assert default.output == {"files": [str(Path("probos", "__init__.py"))]}


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_failure_reply_and_log_name_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected failure is answered with its exception class only, and logged without its text."""
    scene = _scene(tmp_path)
    caplog.set_level(logging.WARNING, logger=swe_tools.__name__)

    def _fails(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError(f"SENTINEL {scene.outside / SECRET_NAME}")

    # raising=False: on the base the module has no resolve_read_path, and the patch changes nothing.
    monkeypatch.setattr(swe_tools, "resolve_read_path", _fails, raising=False)
    result = await _list(scene, [], "*", str(scene.allowed))
    assert result.error == "list_files failed: RuntimeError"
    assert "SENTINEL" not in caplog.text and "secret-name-948" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.xfail(strict=True, reason=_M2)
async def test_an_agent_work_run_lists_inside_the_roots_and_is_refused_outside_them(tmp_path: Path) -> None:
    """The AD-1347 rig with the native tools, read_roots set to the notes' directory and elevated calls
    decided ``auto`` (as S4's WD1): one run lists outside the roots, then inside them."""
    notes = _notes(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    script = [
        _call("list_files", {"pattern": "*", "path": str(outside)}, "c1"),
        _call("list_files", {"pattern": "*.txt", "path": str(notes.parent)}, "c2"),
        _final(ANSWER),
    ]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == []  # premise: both calls ran directly
                assert not _seen(rig, "secret-name-948")
                assert _seen(rig, "outside every readable root") and _seen(rig, "notes.txt")
                assert not _seen(rig, "list_files failed")
        finally:
            await store.stop()
```

### 7.2 M2

**P2-1** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
from probos.security.file_access import (
    FileAccessDenied,
    permitted_read_roots,
    protected_read_roots,
    protected_write_refusal,
    read_verified_file,
    resolve_for_runtime,
    workspace_exempt_roots,
)
```
REPLACE:
```python
from probos.security.file_access import (
    FileAccessDenied,
    permitted_read_roots,
    protected_read_roots,
    protected_write_refusal,
    read_verified_file,
    resolve_for_runtime,
    resolve_read_path,
    workspace_exempt_roots,
)
```

**P2-2** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
class ListFilesTool:
    """AD-544: Glob-search files via FileSearchAgent semantics."""

    tool_id: str = "list_files"
    name: str = "List Files"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "List files in a directory matching a glob pattern."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"files": {"type": "array", "items": {"type": "string"}}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(error="pattern is required")
        path = params.get("path") or "."
        try:
            base = _resolve_path(str(path))
            matches = [str(p.relative_to(_PROJECT_ROOT)) for p in base.glob(pattern)]
            return ToolResult(output={"files": matches})
        except Exception as exc:
            logger.warning(
                (
                    "Strict list-files operation failed reason_code=consumer_failed "
                    "error_type=%s; returning a bounded error"
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else "AD-544 ListFilesTool failed for pattern=%s path=%s: %s"
                ),
                *(
                    (type(exc).__name__,)
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else (pattern, path, exc)
                ),
            )
            return ToolResult(
                error=(
                    "list_files_failed"
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else f"list_files failed: {exc}"
                )
            )
```
REPLACE:
```python
# BF-948: the pattern selects below the base, and the base is where the read policy is asked first.
_LIST_FILES_PATTERN_REFUSAL = (
    "list_files refused: pattern must be a relative glob with no '..' part; "
    "name the directory in path"
)


class ListFilesTool:
    """AD-544: Glob-search files via FileSearchAgent semantics.

    BF-948: under the read policy ``read_file`` applies (``security.file_access``). A
    pattern that is not a str, is anchored or has a ``..`` part is refused. The base
    ``path`` is resolved and refused as ``read_file`` resolves and refuses its path.
    Each match is resolved and listed only if the same policy admits it; a match the
    policy refuses is left out, and nothing names it. A listed match under the project
    tree is given relative to it, any other by its absolute path. Any other failure is
    answered and logged with its exception class only.
    """

    tool_id: str = "list_files"
    name: str = "List Files"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "List files in a directory matching a glob pattern."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"files": {"type": "array", "items": {"type": "string"}}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(error="pattern is required")
        if type(pattern) is not str or Path(pattern).anchor or ".." in Path(pattern).parts:
            return ToolResult(error=_LIST_FILES_PATTERN_REFUSAL)
        path = params.get("path") or "."
        try:
            # BF-948: the roots ``resolve_for_runtime`` composes, composed once per call so
            # the base and every match are decided against the same policy.
            protected = protected_read_roots(self._runtime)
            exempt = workspace_exempt_roots(self._runtime)
            permitted = permitted_read_roots(self._runtime) or None
            try:
                base = resolve_read_path(
                    str(path), protected_roots=protected, exempt_roots=exempt,
                    permitted_roots=permitted, relative_base=_PROJECT_ROOT,
                )
            except FileAccessDenied as exc:
                return ToolResult(error=f"list_files refused: {exc}")
            files: list[str] = []
            for match in base.glob(pattern):
                try:
                    resolve_read_path(
                        str(match), protected_roots=protected, exempt_roots=exempt,
                        permitted_roots=permitted,
                    )
                except FileAccessDenied:
                    continue  # BF-948: refused by the policy, so left out and not counted
                files.append(
                    str(match.relative_to(_PROJECT_ROOT))
                    if match.is_relative_to(_PROJECT_ROOT) else str(match)
                )
            return ToolResult(output={"files": files})
        except Exception as exc:
            kind = type(exc).__name__
            if (context or {}).get("_effect_dispatch_context") is not None:
                logger.warning(
                    "Strict list-files operation failed reason_code=consumer_failed "
                    "error_type=%s; returning a bounded error",
                    kind,
                )
                return ToolResult(error="list_files_failed")
            logger.warning(
                "AD-544 ListFilesTool failed for pattern=%r path=%r error_type=%s; "
                "returning an error ToolResult",
                pattern, path, kind,
            )
            return ToolResult(error=f"list_files failed: {kind}")
```

**P2-3** `src/probos/tools/effect_tiers.py`

SEARCH:
```python
#: Elevated: reads that reach past what the ship holds or past the read policy. find_mcp_tool discovers and offers new
#: tools; web_search, read_page and http_fetch leave the ship (the Captain's Q6, 2026-10-31); list_files resolves its
#: path without the read policy (``swe_harness.tools._resolve_path``).
```
REPLACE:
```python
#: Elevated. find_mcp_tool discovers and offers new tools; web_search, read_page and http_fetch leave the ship (the
#: Captain's Q6, 2026-10-31); list_files is held here until the Captain decides its tier (BF-948, LF4).
```

**P2-4** `tests/test_ad1316_real_effect_routes.py`

SEARCH:
```python
    tool = ListFilesTool(runtime=SimpleNamespace())
    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools._resolve_path",
        lambda _: (_ for _ in ()).throw(RuntimeError("SENTINEL_EXCEPTION_PROSE")),
    )
```
REPLACE:
```python
    tool = ListFilesTool(runtime=SimpleNamespace())
    # BF-948: list_files decides its base through the read policy, so the failure is raised there.
    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools.resolve_read_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("SENTINEL_EXCEPTION_PROSE")),
    )
```

**P2-5** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
_PATTERN_REFUSAL = (
    "list_files refused: pattern must be a relative glob with no '..' part; name the directory in path"
)
_M2 = "BF-948 M2: on the base list_files never asks the read policy"
```
REPLACE:
```python
_PATTERN_REFUSAL = (
    "list_files refused: pattern must be a relative glob with no '..' part; name the directory in path"
)
```

**P2-6** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.parametrize("strict", [pytest.param(False, id="plain"), pytest.param(True, id="strict-dispatch")])
```
REPLACE:
```python
@pytest.mark.parametrize("strict", [pytest.param(False, id="plain"), pytest.param(True, id="strict-dispatch")])
```

**P2-7** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_refusal_is_the_same_whether_the_path_exists(tmp_path: Path) -> None:
```
REPLACE:
```python
async def test_a_refusal_is_the_same_whether_the_path_exists(tmp_path: Path) -> None:
```

**P2-8** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_list_files_lists_a_permitted_root_outside_the_project_tree(tmp_path: Path) -> None:
```
REPLACE:
```python
async def test_list_files_lists_a_permitted_root_outside_the_project_tree(tmp_path: Path) -> None:
```

**P2-9** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.parametrize("pattern", [
```
REPLACE:
```python
@pytest.mark.parametrize("pattern", [
```

**P2-10** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_link_inside_a_permitted_root_to_outside_is_not_listed(tmp_path: Path) -> None:
```
REPLACE:
```python
async def test_a_link_inside_a_permitted_root_to_outside_is_not_listed(tmp_path: Path) -> None:
```

**P2-11** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_the_floor_and_credential_names_are_dropped_with_no_read_roots(tmp_path: Path) -> None:
```
REPLACE:
```python
async def test_the_floor_and_credential_names_are_dropped_with_no_read_roots(tmp_path: Path) -> None:
```

**P2-12** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_a_failure_reply_and_log_name_no_path(
```
REPLACE:
```python
async def test_a_failure_reply_and_log_name_no_path(
```

**P2-13** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
    # raising=False: on the base the module has no resolve_read_path, and the patch changes nothing.
    monkeypatch.setattr(swe_tools, "resolve_read_path", _fails, raising=False)
```
REPLACE:
```python
    monkeypatch.setattr(swe_tools, "resolve_read_path", _fails)
```

**P2-14** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
async def test_an_agent_work_run_lists_inside_the_roots_and_is_refused_outside_them(tmp_path: Path) -> None:
```
REPLACE:
```python
async def test_an_agent_work_run_lists_inside_the_roots_and_is_refused_outside_them(tmp_path: Path) -> None:
```

### 7.3 M3

M3 changes no `src` or `tests` file. Its pairs are P3-1 and P3-2 (§8), plus the ledger.

### 7.4 M4 (Amendment 1)

The detector lines `fault_report.py:401` and `fault_detection.py:296` are **not edited**. AD-1356 S1's RX-6 and RX-7 pin them verbatim, and their comment ("the call's input was wrong") stays true: a refusal is the policy's answer to the call's input.

**P4-1** `src/probos/tools/protocol.py`

SEARCH:
````python
#: AD-1356 S1.2: how a tool marks a caller error. A ``ToolResult.error`` that starts with the tool's own id and this
#: mark (``event_log_query_invalid:window``) says the call's input was wrong. ``fault_report.detect_tool_defect`` and
#: ``fault_detection.collect_tool_fault_batch`` skip such a result.
CALLER_INPUT_ERROR_MARK: str = "_invalid:"


def is_caller_input_error(tool_id: object, error: object) -> bool:
    """AD-1356 S1.2: whether ``error`` is ``tool_id``'s mark of a caller error: both are str, ``tool_id`` is not empty,
    and ``error`` starts with ``tool_id + CALLER_INPUT_ERROR_MARK`` (case-sensitive) and is longer than that prefix."""
    if type(tool_id) is not str or not tool_id or type(error) is not str:
        return False
    prefix = tool_id + CALLER_INPUT_ERROR_MARK
    return len(error) > len(prefix) and error.startswith(prefix)
````
REPLACE:
````python
#: AD-1356 S1.2: how a tool marks a caller error. A ``ToolResult.error`` that starts with the tool's own id and this
#: mark (``event_log_query_invalid:window``) says the call's input was wrong. ``fault_report.detect_tool_defect`` and
#: ``fault_detection.collect_tool_fault_batch`` skip such a result.
CALLER_INPUT_ERROR_MARK: str = "_invalid:"

#: BF-948: how a tool marks its policy's refusal of what the call asked for. A ``ToolResult.error`` that starts with
#: the tool's own id and this mark (``list_files refused: path is outside every readable root``) says the policy
#: answered as designed, so the same two detectors skip it. A tool gives it for its policy's decision only, never for
#: its own failure: ``read_file`` for a ``FileAccessDenied``, ``list_files`` for one and for its pattern rule.
POLICY_REFUSAL_MARK: str = " refused: "


def is_caller_input_error(tool_id: object, error: object) -> bool:
    """AD-1356 S1.2, BF-948: whether ``error`` is ``tool_id``'s mark of a caller error or of its policy's refusal:
    both are str, ``tool_id`` is not empty, and ``error`` starts with ``tool_id`` followed by
    ``CALLER_INPUT_ERROR_MARK`` or ``POLICY_REFUSAL_MARK`` (case-sensitive) and is longer than that prefix."""
    if type(tool_id) is not str or not tool_id or type(error) is not str:
        return False
    return any(
        len(error) > len(prefix) and error.startswith(prefix)
        for prefix in (tool_id + CALLER_INPUT_ERROR_MARK, tool_id + POLICY_REFUSAL_MARK)
    )
````

**P4-2** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
````python
            try:
                target = self.resolve_source_path(str(path))
            except Exception as exc:
                if read is not None and type(read.directive) is RecoverRead:
                    raise WorkspaceResultError("source_changed") from exc
                return ToolResult(error=f"read_file refused: {exc}")
````
REPLACE:
````python
            try:
                target = self.resolve_source_path(str(path))
            except Exception as exc:
                if read is not None and type(read.directive) is RecoverRead:
                    raise WorkspaceResultError("source_changed") from exc
                if not isinstance(exc, FileAccessDenied):
                    raise  # BF-948: only the policy's refusal carries the refusal mark; any other error is a failure
                return ToolResult(error=f"read_file refused: {exc}")
````

**P4-3** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
````python
agent-work run on the AD-1347 rig with the native tools registered. Nothing here replaces the read
policy except T8, which makes it raise to reach the failure handler.
"""
````
REPLACE:
````python
agent-work run on the AD-1347 rig with the native tools registered. Nothing here replaces the read
policy except T8 and T12, which make it raise to reach a failure handler. M4 (T10 to T12): a refusal
the policy decided is not a tool fault on either detector path, and only the policy's refusal is
answered as refused.
"""
````

**P4-4** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
````python
from probos.capability_request import requests_for_work_item
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _rig, _seen
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _chain, _finished
````
REPLACE:
````python
from probos.capability_request import requests_for_work_item
from probos.cognitive.agentic_dispatch import classify_tool_fault_error
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from probos.fault_detection import collect_tool_fault_batch
from probos.fault_report import detect_tool_defect
from probos.tools.protocol import is_caller_input_error
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _rig, _seen, _watch_runs
from tests.test_ad1356_s1_input_errors import _faults
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _chain, _finished
````

**P4-5** `tests/test_bf948_list_files_read_policy.py` (append T10 to T12)

SEARCH:
````python
                assert _seen(rig, "outside every readable root") and _seen(rig, "notes.txt")
                assert not _seen(rig, "list_files failed")
        finally:
            await store.stop()
````
REPLACE:
````python
                assert _seen(rig, "outside every readable root") and _seen(rig, "notes.txt")
                assert not _seen(rig, "list_files failed")
        finally:
            await store.stop()


# --- M4 (Amendment 1): a refusal the policy decided is not a tool fault ---------------------------------


@pytest.mark.parametrize(("tool_id", "error", "marked"), [
    pytest.param("list_files", _OUTSIDE, True, id="list-files-refusal"),
    pytest.param("list_files", _PATTERN_REFUSAL, True, id="pattern-refusal"),
    pytest.param(
        "read_file", "read_file refused: path is protected: the runtime's data directory or a config file", True,
        id="read-file-refusal",
    ),
    pytest.param("event_log_query", "event_log_query_invalid:filter_required", True, id="the-s1-mark-still-holds"),
    pytest.param("list_files", "list_files refused: ", False, id="nothing-after-the-mark"),
    pytest.param("list_files", "list_files refused:x", False, id="no-space-after-the-colon"),
    pytest.param("list_files", "read_file refused: path is outside every readable root", False, id="another-tools-mark"),
    pytest.param("list_files", "List_Files refused: path is outside every readable root", False, id="other-case"),
    pytest.param("list_files", "list_files failed: RuntimeError", False, id="a-failure"),
    pytest.param("list_files", "list_files_failed", False, id="the-strict-failure"),
    pytest.param("", " refused: path is outside every readable root", False, id="no-tool-id"),
])
def test_a_tools_own_refusal_mark_is_not_a_tool_fault(tool_id: str, error: str, marked: bool) -> None:
    """The refusal mark is the tool's own non-empty id, then `` refused: ``, then at least one more character,
    case-sensitive. S1.2's ``_invalid:`` mark is unchanged, and a failure is never marked."""
    assert is_caller_input_error(tool_id, error) is marked


async def test_repeated_refusals_in_an_agent_work_run_file_no_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1's F2 on the AD-1347 rig: two identical ``list_files`` refusals and two identical ``read_file``
    refusals in one run leave the fault store empty, emit nothing, and give the run no tool defect."""
    notes = _notes(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    listing = {"pattern": "*", "path": str(outside)}
    reading = {"path": str(outside / SECRET_NAME)}
    script = [
        _call("list_files", listing, "c1"), _call("list_files", listing, "c2"),
        _call("read_file", reading, "c3"), _call("read_file", reading, "c4"),
        _final(ANSWER),
    ]
    runs = _watch_runs(monkeypatch)
    async with _rig(tmp_path, script) as rig:
        faults, events = _faults(rig)
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == []  # premise: all four calls ran directly
                assert _seen(rig, _OUTSIDE)  # premise: the list_files refusals reached the model
                assert _seen(rig, "read_file refused: path is outside every readable root")  # premise
                assert faults.list_open() == [] and events == []
                assert [run["outcome"].tool_defect for run in runs] == [None]
        finally:
            await store.stop()


def _pairs(*results: Any) -> SimpleNamespace:
    """The loop's pairs for ``read_file`` results, through the adapter it uses."""
    calls = [ToolCallRequest(name="read_file", arguments={}, id=f"r{n}") for n in range(len(results))]
    pairs = [ToolCallResult.from_tool_result(f"r{n}", result, 0.0) for n, result in enumerate(results)]
    assert all(  # premise: the adapter carries each error verbatim as an error
        pair.is_error is True and pair.output == result.error for pair, result in zip(pairs, results, strict=True)
    )
    return SimpleNamespace(tool_calls=calls, tool_results=pairs)


async def test_read_file_answers_refused_only_for_the_policys_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver error that is not the policy's refusal is answered ``read_file failed:`` and still counts: two of
    them are the run's defect, and two real refusals beside them are neither fault nor success evidence."""
    scene = _scene(tmp_path)
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.allowed]))
    refused = await reader.invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise

    def _broken(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError("policy layer broke")

    monkeypatch.setattr(swe_tools, "resolve_for_runtime", _broken)
    broken = await reader.invoke({"path": str(scene.allowed / "ok.txt")})
    assert broken.error == "read_file failed: policy layer broke"
    outcome = _pairs(refused, refused, broken, broken)
    defect = detect_tool_defect(outcome)
    assert defect is not None
    assert (defect.tool_id, defect.error_text, defect.count) == ("read_file", broken.error, 2)
    [evidence] = collect_tool_fault_batch(outcome, classify_error=classify_tool_fault_error).tools
    assert evidence.defect is not None and evidence.defect.error_text == broken.error
    assert evidence.mixed is False and evidence.succeeded is False
````

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-04 (the Revised-by line). If M3 is committed on another local date (`git log -1 --format=%cs`), use that date in both heads.
**Staging:** explicit paths only; `PROGRESS.md` and `DECISIONS.md` may hold unrelated work.

**P3-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-948 (2026-11-04), #1736 -- list_files lists only what the read policy admits.** On the base, `ListFilesTool` resolved its `path` with `_resolve_path` and listed `base.glob(pattern)` without asking the read policy. So with `security_infra.read_roots` set it named files outside the roots: a pattern with `..` returned names above `src/`, and a match outside `src/` came back as an error naming its absolute path, in the reply and, outside a strict dispatch, in a WARNING log line. Now a pattern that is not a str, is anchored or has a `..` part is refused; the base is resolved and refused as `read_file` resolves and refuses its path (the roots, the data-directory and config-file floor, the credential file names); and each match is listed only if the same policy admits it, by its path relative to `src/` or, outside `src/`, by its absolute path. A failure is answered and logged with its exception class only. The tier table is unchanged: `list_files` stays elevated until the Captain decides its tier. No config field. The contract is `prompts/bf-948-list-files-read-policy.md`.

```

**P3-2** `DECISIONS.md`

SEARCH:
```
### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```
REPLACE:
```
### BF-948 -- list_files lists only what the read policy admits (2026-11-04, #1736)

- *Scope.* `cognitive/swe_harness/tools.py` (`ListFilesTool`, `_LIST_FILES_PATTERN_REFUSAL`), `tools/effect_tiers.py` (a comment), tests. Contract `prompts/bf-948-list-files-read-policy.md`.
- *LF1 (the base).* The three root lists `resolve_for_runtime` composes, composed once per call; the base is decided by `resolve_read_path` with `relative_base=_PROJECT_ROOT` and refused with the policy's reason. Rejected: a fresh policy per match; reusing `code_search._ReadFloor`.
- *LF2 (pattern and matches).* A pattern that is not a str, is anchored or has a `..` part is refused; each match is resolved and kept only if the same policy admits it; nothing names or counts a dropped match; a kept match is relative to `src/` when under it, otherwise absolute. Rejected: allowing `..` patterns; a withheld count; refusing the whole call.
- *LF3 (reply and log).* No exception text and no match path in any reply or log line; the strict reply stays `list_files_failed`.
- *LF4 (tier).* Unchanged; moving `list_files` to the read-policy routine set lowers who decides a call, so it is the Captain's decision.
- *LF5 (the class).* `FileSearchAgent`'s caller pattern and `DirectoryListAgent`'s link entries go to BF-944 (#1717) as acceptance cases.
- *Residual.* Recorded limits L1 to L10 of the contract.
- *Reversal.* Revert the BF-948 commits.

### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```

If another entry was inserted directly above BF-946's heading before M3 (BF-949's, for example), BF-948's entry still goes directly above BF-946's heading. That is the only re-anchoring the Builder may do.

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (no BF-948 row; its Bug Tracker lists BFs filed and not fixed).

**M4's tracker pairs (in M4's commit).** They amend the committed M3 text in place. The heads and their dates are unchanged, so the head constraint still holds. Regenerate the ledger afterwards and stage what it writes.

**P4-6** `PROGRESS.md`

SEARCH:
````
A failure is answered and logged with its exception class only. The tier table is unchanged: `list_files` stays elevated until the Captain decides its tier.
````
REPLACE:
````
A failure is answered and logged with its exception class only. A refusal is not a tool fault: `tools/protocol.py` adds `POLICY_REFUSAL_MARK` (the tool's own id, then `" refused: "`) to `is_caller_input_error`, which both fault detectors already consult. So a repeated `list_files refused: …` no longer files an open fault, and neither does `read_file refused: …`, which `read_file` now gives only for the policy's own refusal (any other resolver error is `read_file failed: …` and still counts). The tier table is unchanged: `list_files` stays elevated until the Captain decides its tier.
````

**P4-7** `DECISIONS.md` (two edits, each SEARCH unique)

SEARCH:
````
- *Scope.* `cognitive/swe_harness/tools.py` (`ListFilesTool`, `_LIST_FILES_PATTERN_REFUSAL`), `tools/effect_tiers.py` (a comment), tests. Contract `prompts/bf-948-list-files-read-policy.md`.
````
REPLACE:
````
- *Scope.* `cognitive/swe_harness/tools.py` (`ListFilesTool`, `_LIST_FILES_PATTERN_REFUSAL`, `ReadFileTool`'s refusal handler), `tools/protocol.py` (`POLICY_REFUSAL_MARK`, `is_caller_input_error`), `tools/effect_tiers.py` (a comment), tests. Contract `prompts/bf-948-list-files-read-policy.md` (with Amendment 1).
````

SEARCH:
````
- *LF5 (the class).* `FileSearchAgent`'s caller pattern and `DirectoryListAgent`'s link entries go to BF-944 (#1717) as acceptance cases.
- *Residual.* Recorded limits L1 to L10 of the contract.
````
REPLACE:
````
- *LF5 (the class).* `FileSearchAgent`'s caller pattern and `DirectoryListAgent`'s link entries go to BF-944 (#1717) as acceptance cases.
- *LF7 (refusals are not faults).* A result whose error starts with the tool's own id and `" refused: "` is skipped by `detect_tool_defect` and `collect_tool_fault_batch`, as S1.2's `_invalid:` mark is; the detector lines are unchanged. `read_file` gives the mark only for a `FileAccessDenied`. Rejected: a separate predicate; the classifier (the same-run lane never consults it); an `_invalid:` text; answering a refusal as a success; the mark without the narrowing.
- *Residual.* Recorded limits L1 to L15 of the contract. Path spellings the policy decides differently (review F1) are BF-953.
````

## 9. What this does NOT change

- `security/file_access.py` (the policy, its reasons, the floor).
- `codebase_read_source`, the other native tools, and `register_native_swe_tools`'s permissions. `read_file` changes in one place only (M4, P4-2): a resolver exception that is not a `FileAccessDenied` now reaches its existing failure handlers instead of being answered `read_file refused:`. Its refusals, the `RecoverRead` branch and every other reply are unchanged.
- The detector lines `fault_report.py:401` and `fault_detection.py:296`, `classify_tool_fault_error`, `_NOISE`, and `scripts/replay_approval_tiers.py` (its regex yields only `_invalid:` strings, so its buckets are unchanged).
- `list_files`'s id, name, description and schemas (the AD-1179 and AD-1152 goldens).
- The tier table's sets, `tier_decider`, `direct_tool_ids` and `filed_call_tier`.
- The pool agents (BF-944), the indexed readers (F-202), config, `EventType`, and the strict executor.

## 10. Mutation rows (campaign of record on M2's head)

Line cells hold the source line without its leading indentation. Prefix `LFM` (absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`). All rows are in `src/probos/cognitive/swe_harness/tools.py`.

| Id | Line | Mutate to | Killed by |
|---|---|---|---|
| LFM-1 | `if type(pattern) is not str or Path(pattern).anchor or ".." in Path(pattern).parts:` | `if type(pattern) is not str or Path(pattern).anchor:` | `test_a_pattern_that_climbs_or_is_anchored_is_refused` |
| LFM-2 | the same line | `if type(pattern) is not str or ".." in Path(pattern).parts:` | `test_a_pattern_that_climbs_or_is_anchored_is_refused` |
| LFM-3 | the same line | `if Path(pattern).anchor or ".." in Path(pattern).parts:` | `test_a_pattern_that_climbs_or_is_anchored_is_refused` |
| LFM-4 | `permitted_roots=permitted, relative_base=_PROJECT_ROOT,` | `relative_base=_PROJECT_ROOT,` | `test_list_files_refuses_a_base_outside_every_readable_root` |
| LFM-5 | `permitted_roots=permitted, relative_base=_PROJECT_ROOT,` | `permitted_roots=permitted,` | `test_in_tree_listing_is_unchanged` |
| LFM-6 | `str(match), protected_roots=protected, exempt_roots=exempt,` | `str(match), protected_roots=(), exempt_roots=exempt,` | `test_the_floor_and_credential_names_are_dropped_with_no_read_roots` |
| LFM-7 | `permitted_roots=permitted,` (the whole line, in the loop) | delete the line | `test_a_link_inside_a_permitted_root_to_outside_is_not_listed` |
| LFM-8 | `continue  # BF-948: refused by the policy, so left out and not counted` | `pass` | `test_the_floor_and_credential_names_are_dropped_with_no_read_roots` |
| LFM-9 | `str(match.relative_to(_PROJECT_ROOT))` | `str(match)` | `test_in_tree_listing_is_unchanged` |
| LFM-10 | `if match.is_relative_to(_PROJECT_ROOT) else str(match)` | `if True else str(match)` | `test_list_files_lists_a_permitted_root_outside_the_project_tree` |
| LFM-11 | `return ToolResult(error=f"list_files refused: {exc}")` | `return ToolResult(output={"files": []})` | `test_list_files_refuses_a_base_outside_every_readable_root` |
| LFM-12 | `return ToolResult(error=f"list_files failed: {kind}")` | `return ToolResult(error=f"list_files failed: {exc}")` | `test_a_failure_reply_and_log_name_no_path` |
| LFM-13 | `pattern, path, kind,` | `pattern, path, exc,` | `test_a_failure_reply_and_log_name_no_path` |

**Campaign of record.** Run an unmutated baseline of the new file first, then each row against the new file. Record the base tree and the sha256 of `tools.py`. LFM-5 relies on pytest's working directory not being `src/`. LFM-3 is killed by a `TypeError` raised out of `invoke`, which counts as a failure.

**M4 rows (campaign of record on M4's head).**
- Prefix `RFM` is absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`.
- Run an unmutated baseline of `tests/test_bf948_list_files_read_policy.py` first, then each row against it. RFM-2 also runs `tests/test_ad1356_s1_input_errors.py`.
- Record the base tree and the sha256 of `src/probos/tools/protocol.py` and `src/probos/cognitive/swe_harness/tools.py`.

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| RFM-1 | `tools/protocol.py` | `for prefix in (tool_id + CALLER_INPUT_ERROR_MARK, tool_id + POLICY_REFUSAL_MARK)` | `for prefix in (tool_id + CALLER_INPUT_ERROR_MARK,)` | T10, T11, T12 |
| RFM-2 | `tools/protocol.py` | the same line | `for prefix in (tool_id + POLICY_REFUSAL_MARK,)` | T10 `the-s1-mark-still-holds`; IE4 |
| RFM-3 | `tools/protocol.py` | `POLICY_REFUSAL_MARK: str = " refused: "` | `POLICY_REFUSAL_MARK: str = " refused:"` | T10 `no-space-after-the-colon` |
| RFM-4 | `tools/protocol.py` | `len(error) > len(prefix) and error.startswith(prefix)` | `error.startswith(prefix)` | T10 `nothing-after-the-mark` |
| RFM-5 | `tools/protocol.py` | `if type(tool_id) is not str or not tool_id or type(error) is not str:` | `if type(error) is not str:` | T10 `no-tool-id` |
| RFM-6 | `cognitive/swe_harness/tools.py` | `if not isinstance(exc, FileAccessDenied):` | `if False:` | T12 |
| RFM-7 | `cognitive/swe_harness/tools.py` | `return ToolResult(error=f"read_file refused: {exc}")` | `return ToolResult(error=f"read_file failed: {exc}")` | T11 |

## 11. Recorded limits

- **L1.** The pattern rule is lexical, in the platform's path flavour. Anything a link, a Windows spelling or a component such as `.. ` reaches is decided by the per-match check, which is the authority.
- **L2.** A `**` walk can enter a link or junction and walk its target. What it finds there is dropped, but the walk takes time, a weak timing signal.
- **L3.** Each decision is by path, at the moment of the check. A link retargeted afterwards changes only what a name points to; contents still go through `read_file`'s own check.
- **L4.** The reason "path could not be resolved: <OS text>" can carry the OS error text for the caller's own path, as `read_file`'s does.
- **L5.** The glob and the per-match resolves run synchronously in the event loop, as the glob did before and as `read_file` reads.
- **L6.** The tier stays elevated (LF4).
- **L7.** `FileSearchAgent` (a caller pattern with `..` or a link) and `DirectoryListAgent` (a link entry's target size) are not fixed here (LF5, BF-944).
- **L8.** A base outside `src/`, including `path=".."`, now lists absolute paths. Before, it listed `..`-relative names or an error.
- **L9.** The description is unchanged (two goldens). The model learns the pattern rule from the refusal text.
- **L10.** There is no cap on the number of matches, as before. The cost is one `resolve_read_path` per match.
- **L11.** The refusal mark is lexical and the tool's own. Any tool whose error starts with its id and `" refused: "` is skipped by both detectors. In `src` today only `read_file` and `list_files` emit it (Absence B1). An MCP server's error text could carry its own canonical id and the mark, the same exposure S1.2's `_invalid:` already has.
- **L12.** A refusal is neither fault nor success evidence. A tool that only ever refuses leaves no health evidence, and an agent that keeps asking for a refused path shows in its transcript and trace (AD-1248), not as a fault.
- **L13.** Other answers to the caller's input still count as tool faults. Not changed here; considered, deferred:
  - `codebase_read_source` re-raises its refusal (`tools.py:805-808`);
  - `write_file` and `edit_file` answer `Protected write refused (BF-911): …` (`file_access.py:255`, `:306`, `:311`);
  - `list_files`' `pattern is required` (`tools.py:556`) is unmarked, as on the base.
- **L14.** The policy decides a path by its spelling. In review F1, Windows extended-length and local UNC spellings of a protected path were admitted. BF-953 owns that in `security/file_access.py`, with its own issue, contract and tests over both `ListFilesTool` and `ReadFileTool`. It is built first in this PR, and `list_files` inherits whatever `resolve_read_path` decides.
- **L15.** AD-1356 S1's RX-8 line (`return len(error) > len(prefix) and error.startswith(prefix)`) no longer exists after M4. RFM-4 restates it.

## 12. The Captain's items (the live vessel stays his)

- **Decision (does not block BF-948; LF4).** Should `list_files` join `READ_POLICY_TOOL_IDS` and `ROUTINE_TOOL_IDS`?
  - That makes it routine while `read_roots` is set (run directly under the default `auto`) and critical while it is unset: the Captain, where today a chief decides.
  - Recommended: yes, after BF-948 (and BF-953) merge. It then lists only what the read policy admits, and `read_file` is already routine under the same condition.
  - Given up: the chief's review of listings on a confined vessel. Gained: the six `list_files` filings in the shape of 2026-10-31 stop parking work when confined.
  - It is a table change with its tests: ET1, ET3, and S3's CC tests, which file `list_files`.
- **Live check after merge (reads only).** From a scratch directory outside the checkout, run with the vessel's interpreter and `-I` the following.

  ```python
  import asyncio, os
  from pathlib import Path
  from types import SimpleNamespace
  from probos.config import load_config
  from probos.cognitive.swe_harness.tools import ListFilesTool

  cfg_path = Path(r"<the config the vessel loads>")
  rt = SimpleNamespace(
      config=load_config(cfg_path),
      data_dir=Path(os.environ["LOCALAPPDATA"]) / "ProbOS" / "data",
      config_path=cfg_path,
  )
  for p in (r"<a directory outside every root>", r"<a configured root>", str(rt.data_dir)):
      print(p, asyncio.run(ListFilesTool(rt).invoke({"pattern": "*", "path": p})))
  ```

  - Expected: `list_files refused: path is outside every readable root`; the root's names; `list_files refused: path is protected: …`.
  - `load_config` opens and parses YAML only (`config.py:4154-4160`). The tool lists directory entries. The orchestrator's probe ran the same imports with a redirected home and left no entries in it.
- **Exposure before the fix (optional).** Whether any `list_files` call ran on the vessel with `read_roots` set. Since AD-1356 S2 such calls are filed (elevated); before S2 they ran directly. Not measured here.

## 13. Verified Against Codebase (2026-11-03, on `317fcdc0`)

```
git rev-parse HEAD HEAD^{tree} -> 317fcdc0..., 4ca36294...
Read src/probos/cognitive/swe_harness/tools.py :1-300 (56-64 imports, 79 _PROJECT_ROOT, 245-248 _resolve_path),
  :305-376 (315, 337-341), :380-565 (446-448, 466, 508-565), :730-800 (752-754), :803-924 (825-837, 899-915),
  :1030-1058, :1370-1419 (1380-1385, 1400); wc -l -> 1434
Read src/probos/security/file_access.py :1-440 (73-76, 79-85 str=reason, 105-162, 165-206, 373-411); wc -l -> 989
Read src/probos/tools/effect_tiers.py :1-128 (36-45)
Read src/probos/agents/code_search.py :120-379 (143-166, 323-379); directory_list.py :95-142; file_search.py :115-155
Read src/probos/tools/use_skill_tool.py :165-189; src/probos/cognitive/copilot_adapter.py :95-119, :788-807
Read src/probos/execution/workspace.py :70-109; src/probos/tools/executor.py :835-884, :1005-1054
Read src/probos/config.py :2850-2862, :4154-4160; grep src/probos/tools/protocol.py -> 81-85 ToolResult
Read tests/test_ad1316_real_effect_routes.py :1470-1509; tests/test_ad1344_constitution_write_refusal.py :588-599
Read tests/test_ad544_native_tools.py :1-60; tests/test_ad1356_s2_tool_effect_table.py :1-160
Read tests/test_ad1356_s4_who_decides.py :1-70; grep tests/test_ad1356_s3_chain_of_command.py -> 64-78, 110-118,
  _seen/read_roots at 128, 136, 150, 163, 181, 213, 221, 224, 258, 273, 283
grep/Read tests/test_ad1347_s3_execution.py -> 102-107, 149-237, 284-289; tests/test_ad1356_s1_recovery_reads.py :75-134
Read tests/test_ad1200_instruction_file_access.py :1-55 (36-51 junction helper)
grep tests/fixtures/ad1179_tool_definition_golden.json -> 37; tests/fixtures/ad1152_agentic_off_golden.json -> 845-846
Read scripts/check_architecture_principles.py :545-575 (187-188 limits; categories 573, 608, 632, 741)
grep scripts/gen_ad_ledger.py -> 126-132; Read PROGRESS.md :1-3; grep DECISIONS.md "^### BF-94" -> 904, 1349, 1398
grep .github/workflows/ci.yml -> 17 ubuntu-latest, 47 '3.12'; pyproject.toml :9 >=3.12, :181 asyncio_mode auto
WebFetch CPython 3.12 Lib/pathlib.py and 3.13 Lib/pathlib/_local.py: glob raises NotImplementedError for an anchored
  pattern; 3.12 '..' -> _ParentSelector; select_from returns [] for a non-directory; '**' walks follow_symlinks=False
gh issue view 1736 (title, OPEN); gh issue view 1717 (BF-944 body); gh issue view 1523 --comments (F-202 :1260, F-211 :1324)
logs/bf948/probe-evidence-head-317fcdc0.txt (PREMISES HELD, exit 0); git ls-files src | wc -l -> 1098
```

## Absence Verified (2026-11-03, on `317fcdc0`)

```
A1 CLAIM: the classes in src/probos that declare `tool_id: str = "<non-empty id>"` are the 12 in swe_harness/tools.py.
   RUN:   Grep 'tool_id: str = "' over src/probos
   FOUND: tools.py:415, 511, 571, 610, 655, 693, 731, 849, 930, 976, 1064, 1194; empty defaults at agent_work_tags.py:134,
          fault_report.py:228, :514, execution/effect_types.py:45 (resolved_tool_id), repair_brief.py:90,
          repair_verification.py:42
   HOLDS: yes for that spelling; tools that declare tool_id otherwise are not covered by this RUN
A2 CLAIM: in src/probos/agents, src/probos/tools, src/probos/cognitive/swe_harness and cognitive/copilot_adapter.py the
          directory walks are exactly the ones in LF5's table.
   RUN:   Grep '\.r?glob\(|\.iterdir\(|os\.listdir\(|os\.walk\(|os\.scandir\(|iter_files\(' over each of those paths
   FOUND: agents/code_search.py:269, agents/file_search.py:141, :145, agents/directory_list.py:120;
          tools/code_execution_tool.py:1198, tools/browser/session.py:345, tools/browser/recording_reaper.py:97, :101, :171,
          tools/use_skill_tool.py:184; swe_harness/tools.py:543; copilot_adapter.py:800
   HOLDS: yes for those paths; 45 other files under src/probos match and were not classified
A3 CLAIM: no src code reads a `files` key from a list_files result.
   RUN:   Grep '\[\s*["']files["']\s*\]|\.get\(\s*["']files["']' over src/probos; Grep 'list_files' over src/probos
   FOUND: cloud_pickers/google_drive.py:148 (a Drive payload); __main__.py:2739, 2860, 2920, 3137, 3227, 3325 (reset tiers);
          list_files: cloud_pickers (provider methods), execution/workspace.py:26, 438, 464, routers/agents.py:1426,
          routers/cloud_pickers.py:221, 232, config_models/experience.py:318, tools/effect_tiers.py:41, 44,
          swe_harness/native_builder.py:50 (a tool id), tools.py:511, 561, 563
   HOLDS: yes for those spellings
A4 CLAIM: the only test that names a line M2 edits in tools.py is test_ad1316_real_effect_routes.py:1485.
   RUN:   Grep 'relative_to\(_PROJECT_ROOT\)|base\.glob|_resolve_path\(str\(path\)\)|AD-544 ListFilesTool failed|
          Glob-search files|list_files_failed|list_files failed' over tests; Grep '_resolve_path|Strict list-files|
          consumer_failed' over tests
   FOUND: test_ci_shard_pytest_plugin.py:169 (its own base.glob); test_ad1316:967 (another route), :1485, :1495;
          test_ad721g_baseline_vrms.py (another _resolve_path); test_bf758_file_read_confinement.py:400 (a docstring)
   HOLDS: yes
A5 CLAIM: list_files' description and schema are pinned in two goldens, and no test outside AD-1356 runs list_files through an agent.
   RUN:   Grep 'list_files|ListFilesTool' over tests
   FOUND: goldens ad1179:37, ad1152:845; test_ad1179_tool_schema_golden.py:51, :127; test_ad1316:25, :1479, :1483;
          test_ad1344:595 (docstring); test_ad1356_replay_approval_tiers.py:53, :62 (classification);
          test_ad1356_s1_recovery_reads.py:93 (a recovery-read predicate); test_ad1356_s2:89-148; s3:118-159; s4:41-44;
          test_ad543_tool_call_protocol.py:238; test_ad544_native_tools.py:17-134; the rest are WorkspaceManager or cloud pickers
   HOLDS: yes
A6 CLAIM: no name this contract adds exists, and the LF prefixes are unused.
   RUN:   Grep '_LIST_FILES_PATTERN_REFUSAL|_list_files_pattern|test_bf948|bf-948-list-files|list_files refused' over the repo;
          Glob prompts/bf-94*; Grep '\bLF-?[0-9]+\b|\bLFM-[0-9]|\bLFT[0-9]|\bLFL[0-9]' over prompts/, DECISIONS.md, PROGRESS.md
   FOUND: none; bf-941, bf-946, bf-947 prompts; none
   HOLDS: yes
A7 CLAIM: tools.py does not import or call resolve_read_path.
   RUN:   Grep 'resolve_for_runtime|resolve_read_path\(|permitted_read_roots|protected_read_roots\(|workspace_exempt_roots\(' over src
   FOUND: tools.py:58, 62, 315, 338-340, 448, 754, 912-914; no resolve_read_path in tools.py
   HOLDS: yes
A8 CLAIM: no census test pins the callers of resolve_read_path or resolve_for_runtime by call site.
   RUN:   Grep 'resolve_read_path|resolve_for_runtime' over tests (files); then content of test_bf908_floor_and_children.py
   FOUND: test_bf908_floor_and_children.py, test_bf758_file_read_confinement.py, test_ad1200_repository_instructions.py,
          test_ad1200_instruction_file_access.py; the bf908 hits concern _ReadFloor and code_search
   HOLDS: yes for bf908; bf758 and the ad1200 files were not read line by line (G2 runs bf758)
```

**Not verified (the orchestrator measures):**
- G1's counts, and that each of the 16 xfails fails on the base for its marker's reason (the strict T1 cases by `list_files_failed`).
- The venv's Python version. The `glob` behaviour above was read from CPython 3.12 and 3.13 source; whether `**` enters a junction on that interpreter.
- That the probe's tree (`701cabcd` in its log) had `tools.py` and `file_access.py` byte-identical to `317fcdc0`.
- That the AD-1347 rig shows a tool's error text verbatim to the model (T9's `_seen`). S4's WD1 passing on the base through the error text suggests it does.
- The cost of `list_files("**/*", ".")` before and after on the checkout. 1098 tracked files under `src`, plus `__pycache__`.
- The live `read_roots`.

## 13a. Verified for Amendment 1 (2026-11-04, on `9649df65`)

```
git log --oneline -6 -> 9649df65 head; 5517cd34 M3, 60177ff7 M2, b70d8b14 M1, 9d685dac contract; base ca0ca20b
git diff ca0ca20b 9649df65 -- tools/protocol.py fault_report.py fault_detection.py security/file_access.py -> empty
Read logs/bf948/review-r1-report.md (F1-F3)
Read src/probos/tools/protocol.py :78-112 (94-97 mark, 100-106 is_caller_input_error)
Read src/probos/fault_report.py :340-430 (401 the skip, 392-416 tally, no classifier), :448-465 (462 resolve_tool_defect)
Read src/probos/fault_detection.py :1-60 (24 import, 32-35 _NOISE), :240-347 (266 same_run, 296-297 skip, 315 noise),
  :455-492 (observe_completed_tool_run)
Read src/probos/cognitive/agentic_dispatch.py :2145-2166 (classify_tool_fault_error: exact host refusals only),
  :4366-4421 (4351 _defect_outcome, 4376 detect_tool_defect, 4415 observe_completed_tool_run)
Read src/probos/tools/executor.py :326-364 (classify_tool_error: no signature matches the refusal texts -> "other")
Read src/probos/cognitive/swe_harness/tools.py :440-506 (447-449, 460-467 any Exception -> "read_file refused",
  490-506 outer handlers), :798-811 (805-808 codebase_read_source re-raises); grep -> 555-557, 571
Read src/probos/security/file_access.py :76-162 (79-85; 134-161 every refusal raises FileAccessDenied)
Read scripts/replay_approval_tiers.py :40-103 (55 import, 59 _INPUT_MARK, 100 call)
Read tests/test_ad1356_s1_input_errors.py :1-163 (_faults 35-39, IE1 55-73, IE3 97-126, IE4 130-145, IE5 149-162)
Read tests/test_ad1156_plan_execute_mode.py :826-843 (host refusals, another mechanism)
grep tests/test_ad1347_s3_execution.py -> _call 102, _final 106, _rig 150, _seen 284, _watch_runs 311
grep tests/test_ad1356_s2_tool_effect_table.py -> _native 56, _self_task 68, _notes 78; s3 -> _chain 64, _finished 110
grep src/probos/cognitive/swe_harness/tool_call.py -> ToolCallRequest 670-676, ToolCallResult 680-692 (no name field),
  from_tool_result 696-734
Read tests/test_bf948_list_files_read_policy.py :1-34, :210-239; Read DECISIONS.md :1361-1371; grep PROGRESS.md :3
grep prompts/ad-1356-s1-stop-filing-what-a-rule-decides.md -> RX-8 1198, RX-9 1199
Glob tests/test_ad1356_replay_approval_tiers.py -> exists
scripts/ad_ceiling.py -> CEILING AD-1358 (issue titles), NEXT AD-1359; nothing allocated here
gh issue list --search "BF-953 in:title" -> []; Glob prompts/bf-95* -> none (BF-953 is drafted elsewhere)
```

## Absence Verified (Amendment 1, 2026-11-04, on `9649df65`)

```
B1 CLAIM: only read_file and list_files give a ToolResult error that starts with their own id and " refused: ".
   RUN:   Grep 'refused: ' over src/probos; Grep 'ToolResult\(error=f?["'][a-z_]+ refused' over src/probos
   FOUND: tools.py:467, 511, 572; the other hits are log lines, console prints, docstrings, route details
          (approval_authority.py:46, decision_pre_clearances.py:52) and BF-911's "Protected write refused"
          (file_access.py:255, 306, 311), none starting with a tool id
   HOLDS: yes for literal and f-string spellings; an error built only from exception text was not enumerated
B2 CLAIM: the consumers of is_caller_input_error are fault_report.py:401, fault_detection.py:296,
          scripts/replay_approval_tiers.py:100 and tests/test_ad1356_s1_input_errors.py:145.
   RUN:   Grep 'CALLER_INPUT_ERROR_MARK|is_caller_input_error' over the repo; over ui, scripts, docs, config
   FOUND: those four, plus prompts and trackers
   HOLDS: yes
B3 CLAIM: the detectors' callers are agentic_dispatch.py:4376, :4415, fault_report.py:462, fault_detection.py:266, :467,
          native_builder.py:181.
   RUN:   Grep 'detect_tool_defect\(|collect_tool_fault_batch\(|observe_completed_tool_run\(' over src/probos
   FOUND: those
   HOLDS: yes
B4 CLAIM: no test expects "read_file refused:" for a non-FileAccessDenied, and none pins an own-id refusal as a fault.
   RUN:   Grep 'read_file refused|list_files refused| refused: ' over tests; Grep 'refused' over test_ad1164/1169/1189/
          1205/1257/1279; Grep resolver raises in test_ad1240_tool_result_delivery.py
   FOUND: bf948 :28-31, :107, :164 (FileAccessDenied); ad1189's _REFUSAL (a host refusal); ad1240's resolver
          doubles raise FileAccessDenied (:1355, :3364, :3457), its other raises are in reads (:1236-1238, :3271-3273)
   HOLDS: yes
B5 CLAIM: no test reads the source lines M4 edits.
   RUN:   Grep 'type\(read\.directive\) is RecoverRead|is_caller_input_error\(tool, raw_text\)|prefix = tool_id' over tests
   FOUND: test_ad1240:953, 1335, 1396, 1417 (runtime asserts, not source scans)
   HOLDS: yes
B6 CLAIM: FileAccessDenied has no subclass in src.
   RUN:   Grep 'class FileAccessDenied|\(FileAccessDenied\)' over src/probos
   FOUND: file_access.py:79 only
   HOLDS: yes
B7 CLAIM: M4's names and prefix are free.
   RUN:   Grep 'RFM-[0-9]|RFT[0-9]|POLICY_REFUSAL_MARK|is_policy_refusal|refusals_are_not|test_bf948_.*fault' over
          prompts, DECISIONS.md, PROGRESS.md, src, tests, scripts
   FOUND: tests/test_ad1156_plan_execute_mode.py:830 (another test's name) only
   HOLDS: yes
```

**Not verified (the orchestrator measures):**
- G4's counts, including the red step.
- That T11 fails on the BF-953 head through the rig's real observer. The reviewer measured the fault with the production detectors and a real store, not on this rig.
- BF-953's final diff.
- `from_tool_result` carrying the error verbatim (T12 asserts it as a premise).

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:**
  - srp-size is per class (`:556-575`, limits 500 lines and 15 methods, `:187-188`). `ListFilesTool` grows from 58 lines to about 85 and keeps 2 methods.
  - No new import module: `file_access` is already imported.
  - Only public names cross a module.
  - The new test reads no source text.
- **`check_dormant_classes.py`:** no `src` class added.
- **Goldens:** the description and schemas are unchanged (A5).
- **Config:** none. **EventType:** none.
- **`gen_ad_ledger.py --check`:** passes once M3 regenerates; the heads carry no status keyword in their first 120 characters.
- **Collection:** one new test file. M1's strict xfails keep G1 green on the base.

## 15. Prior Art and Blind Spots

- **Internal:**
  - BF-758, the floor and policy split; resolve before containment (`file_access.py:130-133`).
  - BF-908, composing the roots once and deciding each result path (`_ReadFloor`); "a root can hold a protected file" (`code_search.py:365-367`), which is why a match is checked and not only the base.
  - BF-910, fixed texts and the exception class only.
  - AD-1316, the strict bounded reply.
  - AD-1356 S2, the tier hold and its L4.
  - F-211 (#1523), the first record of this gap; F-202, the indexed readers.
- **External:** skipped. This is ProbOS-specific plumbing with no outside design question. Considered, deferred: every overdue row of `docs/research/reference-projects.md` (date used 2026-11-03), none relevant to a BF.
- **Blind spots found:**
  1. A permitted root outside `src/` could not be listed at all. The fix needs a reply form (LF2).
  2. A dropped-match count would be an oracle.
  3. A match must be checked as well as the base: links, and a root holding the floor.
  4. S3's and S4's `list_files` tests pass on the base through the defect's error text (LF6).
  5. `effect_tiers.py:41-42` becomes false (P2-3).
  6. `FileSearchAgent`'s caller pattern has the same match-escape shape (LF5, to BF-944).

## 16. Diff Reviewer: properties to verify

1. A pattern that is not an exact str, is anchored or has a `..` part is refused before any filesystem call. It gets the fixed text, except that a falsy pattern of any type (`""`, `None`, `False`, `0`, `[]`, `{}`) is answered `pattern is required` by the check that precedes the pattern rule (`tools.py:555`).
2. The base is decided by `resolve_read_path` with exactly the roots `resolve_for_runtime` composes (`file_access.py:405-411`) and `relative_base=_PROJECT_ROOT`. A refusal returns `list_files refused: ` plus the policy's reason, lists nothing and logs nothing.
3. Every listed entry's resolved path is admitted by the same three root lists. A refused match leaves no name and no count in the reply or the log.
4. A listed entry under `_PROJECT_ROOT` is relative to it; any other is absolute. In-tree output is unchanged.
5. No reply or log line carries an exception's text or a match's path. The strict reply is still `list_files_failed`, and the strict log line still omits the pattern and the path.
6. `list_files`' id, name, description, schemas and registration, `file_access.py`, and the tier table's sets and functions are unchanged; P2-3 is a comment.
7. No config field, `EventType`, persisted key, `src` class or method is added.
8. Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order.
9. Each test whose xfail mark M2 removes failed on the base for the reason its marker names. T7 passes on the base.
10. M4: `is_caller_input_error` marks exactly `<own non-empty id>` + `_invalid:` or `" refused: "` + at least one character, case-sensitive. The detector lines `fault_report.py:401` and `fault_detection.py:296` are byte-identical to the base, and a marked refusal is neither fault nor success evidence on both lanes.
11. M4: `read_file` answers `read_file refused:` only for a `FileAccessDenied`. Any other resolver exception reaches the existing handlers (`File not found:` or `read_file failed:`). The `RecoverRead` branch still raises `source_changed`.
12. M4: no tool other than `read_file` and `list_files` emits the mark, `scripts/replay_approval_tiers.py`'s buckets are unchanged, and T10 to T12 failed on the BF-953 head as G4's red step names.

## 17. Acceptance criteria

1. With `read_roots` set, `list_files` over a base outside them (absolute, with `..`, in another case, through a link) or with a climbing or anchored pattern lists nothing outside them, and its reply names no file: T1, T2, T4, T5.
2. With `read_roots` empty, the floor and the credential-name rule apply (T6), and in-tree behaviour is unchanged (T7). A permitted root outside `src/` is listed (T3).
3. A failure is answered and logged with its exception class only (T8). The AD-1316 strict-log test passes as rewritten.
4. One agent-work run on the real executor lists inside the roots and is refused outside them (T9).
5. Repeated `list_files` and `read_file` refusals in one agent-work run file no fault and give no tool defect (T11). A resolver failure that is not the policy's refusal is answered `read_file failed:` and still counts beside skipped refusals (T12). The mark is the tool's own (T10).
6. Every §10 mutant, LFM and RFM, is killed. G1 to G4 and the §14 checks pass, and the broad gate's receipt is green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
