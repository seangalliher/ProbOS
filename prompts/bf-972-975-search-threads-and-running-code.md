# Search threads and running code: searches check the read policy off the event loop, and agent writers are denied the running package -- #1803, #1806, one batch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Revision R2 (2026-11-16, after review round 1).** Review round 1 found three things, and R2 answers each:
- write_file and edit_file gave the documents rule's refusal without their refusal mark (`tools/protocol.py:99-115`), so two identical refusals in one run were a tool defect to both fault detectors. The base did the same for BF-943's documents; this batch adds refusals that a build model reaches by a relative `probos/...` path (D10). R2 marks the documents rule's refusal at both sites (D14, P-R2-1, P-R2-2), adds R14 with rows W6 and W7, and records the constitution and protected-configuration refusals at those sites as L9.
- D2 put the subprocess between code search's two worker calls; it comes before both.
- `_LoopProbe.run` used `asyncio.ensure_future`; it now uses `asyncio.create_task`.
The copy in N1-1 carries R2's test changes. The orchestrator applied R2's pairs by tool on a scratch tree (base `ecec9031`, tree `dca4f150`) and measured G-R2 and the 15 mutation rows on a Windows host whose volume makes no 8.3 names; the measured values are in section 4's G-R2 and in 7b.
**Revision (2026-11-16, three rounds).** The orchestrator applied every pair and the new file by tool on a scratch tree (base `e0843f4f`, tree `2e8120b8`) and ran G1, G2a, G2b and the 13 mutation rows on a Windows host whose volume makes no 8.3 names. This revision puts those measured values in place of the expected ones, restates the Status line and the section 11 heading, and writes out M2b's commit paragraph. It corrects these statements:
- section 4's `test_bf908` count;
- the config search in Absence Verified;
- W1's killed set in 7b;
- the ui-fixtures row and its Absence Verified claim;
- a commit id that only a scratch object store held;
- "three lists" for `ReadFloor`'s attributes, in the prose and in M2a's `ReadFloor` docstring (A1-45);
- a token in P3-2's Rollout bullet;
- an unshown cost claim in P3-1's Base bullet;
- the native build loop sentence in P3-1 and L6;
- "bounded walk" in P3-2;
- "No case bounds a duration" in M1's module docstring, where the probe's wait has a 10 s ceiling (A1-46);
- "no module holds" in M1's `_ABSENT_TEXT` and R2's docstring, where the test module holds that text (A1-47, A1-48);
- "moved unchanged" in `_rg_result`'s docstring, where `proc.returncode` became a parameter (A1-49);
- an install-layout claim no test ran, and "reads nothing", in M2b's comments (A1-50, A1-51).
The code changes are those six places, in comments, docstrings and one test constant; M3's tracker texts change. R8 has run nowhere yet. The second round, after the orchestrator checked each figure and name the first round added, replaced the first round's unmeasured predictions and overclaims with what was measured. The third round brought the code blocks' own comments, docstrings and one test string in line with what the code and the measurements show.
**File in the repository:** `prompts/bf-972-975-search-threads-and-running-code.md`. No commit subject or tracker line in this batch carries an `AD-` or `BF-` token or this file's name (section 5).
**Status:** ready to build on `origin/main` once batch 4 (#1792, #1793) and #1798 have merged. The Architect read the code on `2b7cb330` (tree `d837f4cf`). The base is batch 4's final head, `e0843f4f` (tree `2e8120b8`). `git diff --name-only 2b7cb330 e0843f4f` lists `DECISIONS.md`, `prompts/bf-962-963-ward-room-identity-keys.md` and `tests/fixtures/ad1152_agentic_off_golden.json`, and each base blob below is the same at `e0843f4f` (orchestrator, 2026-11-16). #1798 (`storage_gate.py`, its new test file and its tracker entries) merges first and edits none of the source or test files this contract names. Its tracker entries move `PROGRESS.md` and `DECISIONS.md`, whose anchors here are text, not line numbers (M3).
**Dependencies:** batch 1 (#1799, #1802, #1805, merged `250a70d5`) is in the base: `builder_paths.is_reserved_device_name` and `file_writer.commit_write`'s temporary-file write. **Numbers:** #1803 is BF-972 and #1806 is BF-975. Nothing is allocated here.
**Builder:** `claude-sonnet-5.5`, at most about 150 tool calls per milestone. Search first, then read the range. The Builder runs no pytest; the orchestrator runs every gate. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Tests (measured 2026-11-16 by the orchestrator on a Windows host whose volume makes no 8.3 names, `-n 0 -p no:randomly`):** one new file, `tests/test_search_threads_and_running_code.py`, with 44 cases on Windows through M3; R2 adds R14's six, for 50 (measured at R2: 49 passed, 1 skipped). At M1: 8 passed, 1 skipped and 35 xfailed. The skip is R8, which skips on a volume that makes no 8.3 names. It skipped here, has run nowhere yet, and is not in the measured sets. No existing test is edited and none is removed.

**Base blobs (read on `2b7cb330`; the orchestrator found each one the same at `e0843f4f`, 2026-11-16).**

| File | Blob | Milestone |
|---|---|---|
| `src/probos/security/file_access.py` | `180d3a5d806cfd6c652bfd7d646984011df7a5d8` | M2a |
| `src/probos/agents/file_search.py` | `18e07712115f4d93ba49c718781c4444635019a1` | M2a |
| `src/probos/agents/code_search.py` | `e59ee7b2f306fe3adb66ef3638dafbd6e5283ca4` | M2a |
| `src/probos/cognitive/swe_harness/tools.py` | `681322dffe3fa362d585b99a7c035633be851f1f` | M2a |
| `src/probos/cognitive/builder_paths.py` | `8d8e46120df2e3db4b835cf83733e5d4f813b434` | M2b |
| `PROGRESS.md`, `DECISIONS.md` | move with the earlier batches | M3 (text anchors) |

## 1. Problem (re-derived on `2b7cb330`)

| Issue | Evidence | Verdict |
|---|---|---|
| #1803: the policy check costs one resolution per match, with or without `read_roots` | `file_access.py:653-673` (`ReadFloor`); `:362` (`candidate.resolve()`); `:370` (a fresh `_OnDisk` on every call) | Holds |
| #1803: file search walks and checks on the loop | `file_search.py:112` is an `async def` with no `await` in `:112-162`, the whole method (re-checked on `e0843f4f`); the walk is at `:140-147` and the check at `:150-151` | Holds |
| #1803: code search | `code_search.py:227` (each rg line), `:285` (each file in the Python engine), `:378` (each result in `_within_floor`, called at `:164` and `:166`) | Holds |
| #1803: list_files has no cap | `tools.py:583-597` (`for match in base.glob(pattern)`) | Holds |
| #1806: write_file roots a relative path at `<checkout>/src` | `tools.py:81`, `:247-250` | Holds |
| #1806: the eight sites call one rule | `tools.py:1069`, `:1166`; `file_writer.py:120`, `:167`; `skill_framework.py:214`, `:274`, `:429`, `:562` | Holds (the issue's `file_writer` lines were `:112,116,159,163` on `5275d008`) |
| #1806: no code entry and no `.env` in the list | `builder_paths.py:216-234` | Holds |
| #1806: `.env` is loaded at start | `__main__.py:4187-4188`: `load_dotenv()` with no path. The installed `dotenv/main.py:332-372` (`find_dotenv`) walks from the calling file's directory up to the root and loads the first `.env` it finds; under a debugger, interactively or frozen, it starts at the working directory instead | Holds, and it is wider than the issue states: `<checkout>/src/.env` is found before `<checkout>/.env` (D7) |

## 2. Solution overview

- **M2a (#1803).**
  - Each search runs its walk, each match's policy check and its sort in a worker thread through `asyncio.to_thread`. The policy is unchanged.
  - `list_files` examines at most 20,000 glob matches and says when more match.
  - `ReadFloor(None)` logs one WARNING per process.
- **M2b (#1806).**
  - `captain_document_write_refusal` gets one predicate, `_names_running_code`, called on the path as written and once resolved, in the try block that already judges both forms.
  - It refuses a path at or below the running package directory, and a `.env` file in that directory or in any directory above it.
  - `".env"` is added to `CAPTAIN_DOCUMENT_PATHS`, so the writer's root and the running checkout hold it too.
  - The eight sites, their reason code and their log lines are unchanged; write_file and edit_file give the rule's refusal after their refusal mark (D14, R2).
- **Rejected:**
  - A semaphore or a dedicated executor for searches. A module-level asyncio primitive is shared across event loops, and a dedicated pool needs a shutdown lifecycle. L2 records the residual.
  - Adding `"src/"` to `CAPTAIN_DOCUMENT_PATHS` (the issue's option b): it would refuse a user's own `<cwd>/src`.
  - Protecting only the rule's own modules (option c).
  - Scanning the package for hard links (L4).
  - AD-548's `blocked_paths` hook (the issue's reasons).

## 3. Decisions

| # | Question | Decision and evidence |
|---|---|---|
| D1 | Thread safety | `resolve_read_path` (`:312`) reads its arguments, the filesystem and module constants (`_PROTECTED_LEAF_KEYS`, compiled patterns); its per-call state is one `_OnDisk` (`:370`). In `file_access.py` a search for `lru_cache` and `_windows_file_api(` gives 5 lines on `e0843f4f`: the import (`:53`), the cached `_windows_file_api` (`:796-797`) and its two calls (`:823`, `:847`), on the instruction reader, not on this path. `ReadFloor` sets three attributes in `__init__` (`:658-660`; `_permitted` may be `None`) and reads them in `permits` (`:662-673`). `code_search._ReadFloor._decided` (`:343`) is written by one thread at a time. The floor `act` builds on the loop goes to worker calls that run one after another: the rg parse, then the Python engine if rg's output does not parse. Each final-check floor is built inside its own worker call. `reader_spelling`'s docstring says it calls no filesystem function (`:203`). A search for `lru_cache`, `global ` and `threading` in `file_walk.py` and in `safe_regex.py` gives 0 lines in each on `e0843f4f`. Logging is thread-safe. Admission's `check_at` stays on the loop (`code_search.py:198`); the parse after the subprocess moves |
| D2 | One `to_thread` per search, cancellation and the executor | file_search, list_files and code search's Python path make one call each (code search's Python engine and its final check share the call). Code search's rg path makes two, in this order: `_search_rg` awaits the subprocess on the loop and then makes the first (the parse with its floor check, `_rg_result`), and `act` makes the second (the final check, `_final_check`) on the result `_search_rg` returned. `_search_rg` must still return the unchecked result that `test_bf908...:391` compares. A cancelled search's thread runs to the end of its walk and its result is dropped. `iter_files` stops at 20,000 files (`file_walk.py:47`, `:186`), list_files gets a 20,000-match cap, and the Python engine also stops at `max_results` (at most 5,000, `code_search.py:128`). File search with `include_ignored=true` uses a raw `rglob` with no cap, as on the base (L1). The default executor is Python's `ThreadPoolExecutor` default (`min(32, cpu_count + 4)` workers, from the Python documentation). `git grep -n set_default_executor e0843f4f -- src` gives 1 line, `audio/tts/resident.py:20`, a line of that module's docstring. The searches share the pool with the other `src` calls into it (count and pattern in L2), so many concurrent broad searches can delay them, while the loop itself stays live |
| D3 | list_files cap | `_LIST_FILES_MAX_MATCHES = DEFAULT_MAX_FILES` (20,000), read at call time. It counts glob matches examined, refused ones included. When a further match exists, the listing stops and the output gains `"truncated": True` and a `"note"`: `list_files stopped after examining 20000 matches; at least one more match was not examined. Narrow the pattern or the path.` The number left out is not known without the walk the cap avoids, so the note says "at least one more" (L8). A listing that is not truncated stays exactly `{"files": [...]}` (`test_bf948...:208` pins that shape; S4's control). `output_schema` and the description are unchanged, so the tool-definition goldens do not move (`ad1179_tool_definition_golden.json:37`; `ad1152_agentic_off_golden.json:845`, the same line at `e0843f4f`). `test_ad1179_tool_schema_golden.py` and `test_ad1152_agentic_correlation.py` were among the 30 other files of G2a (1246 passed, 27 skipped at the base and at M2a) |
| D4 | `ReadFloor(None)` warns once | The module-level `_NO_RUNTIME_WARNED` flag is set under the `threading.Lock` `_NO_RUNTIME_LOCK`, so a floor built on a worker thread and one built on the loop log once between them. A test resets it with `monkeypatch.setattr(file_access, "_NO_RUNTIME_WARNED", False)`. Message: `BF-972: read policy without a runtime; operator read_roots not applied (the floor still applies)`. `code_search._ReadFloor` is its own class and does not warn (L3) |
| D5 | Acceptance test | `_LoopProbe` (section 7). The wrapped policy check records on every call whether it ran on the loop's thread (`asyncio.get_running_loop()` raises in a worker thread). Its first call waits up to 10 s on a `threading.Event` that only a coroutine on the loop sets. In a worker thread the wait ends at the next 5 ms tick. On the loop it cannot end early, because the setter cannot run. The probe therefore tells the two apart by which thread runs the check, not by a duration. The 10 s is a ceiling only a broken build reaches |
| D6 | Package directory | `_RUNNING_PACKAGE = Path(__file__).resolve().parents[1]` in `builder_paths.py`, which equals `Path(probos.__file__).resolve().parent` (R0 pins it; R0 passed at G2b) without a module-level `import probos`. For a checkout it is `<checkout>/src/probos`; for an editable install, the `src/probos` its `.pth` names; for an installed package, `site-packages/probos`. This host's venv `.pth` holds `D:\ProbOS\src` (`__editable__.probos-0.1.0.pth`), so a run without `PYTHONPATH` imports `D:\ProbOS\src\probos`; the gate sets `PYTHONPATH` to the worktree's `src` (`run_test_gate.py:818`). Comparison uses `_document_parts` on both sides, as `_names_a_document` does: upper-case canonical form, a `:` stream suffix dropped from each component, trailing dots and spaces dropped, and the extended-length and `\\?\UNC\` prefixes removed. Both the written form (`os.path.abspath`) and the resolved form (`_resolve`) are judged. A link into the package is meant to be caught on the resolved form, because `_resolve` follows links. R6 passed at G2b on Windows, where it makes a junction; its symlink form runs on other systems and has not run here. A short 8.3 name is meant to be caught there too, because `_resolve` expands existing parts; R8, its case, skipped here and has run nowhere yet. A share spelling (`\\localhost\D$\...`) is not compared by identity, as with the documents (L7) |
| D7 | `.env`: where | (a) In the package directory or in any directory above it: the directories `load_dotenv()` searches when the vessel starts from `__main__.py`, nearest first (it loads the first `.env` found, so `<checkout>/src/.env` would replace `<checkout>/.env`). (b) At the writer's root and the running checkout, through the new `CAPTAIN_DOCUMENT_PATHS` entry: the working directory for `file_writer` and the office writers (the debugger and interactive start), and `<checkout>/src` for write_file and edit_file. A `.env` in a subdirectory, or in a tree that is neither of these, is not refused (R11): the start-up `load_dotenv()` does not search it. Because (a) also covers `<checkout>/.env`, the issue's mutation "removing step 2 fails the .env test" is killed by the writer-root case (R10; W3 measured) |
| D8 | The eight sites, checked | `tools.py:1069` (write_file, root `_PROJECT_ROOT`), `:1166` (edit_file, same root): `ToolResult(error=...)` and log `reason_code=captain_document_refused`. `file_writer.py:120` (propose_write) and `:167` (commit_write), root `Path.cwd()`: a `{"success": False, "error": ...}` dict. `skill_framework.py:214` (docx_create), `:274` (docx_revise), `:429` (pptx_create), `:562` (xlsx_update), root `Path.cwd()`: `raise PermissionError(refused)`. Each passes the path it will write and returns or raises the rule's text, so one change to the rule reaches all eight. R3 and R4 drive all eight on a package path. No site is edited at M2b; R2 prefixes write_file's and edit_file's answer to the rule with their refusal mark (D14) |
| D9 | Control | R12: a temporary `tree/src/probos/` outside the package, with the working directory in `tree`; commit_write, docx_create and write_file write into it |
| D10 | Self-build | Not confirmed as the question was put. `native_builder.py:47-57` offers the registered `write_file` and `edit_file` to the build loop, and its relative paths land under the live `<checkout>/src` (`tools.py:247-250`). Before this change, a build model's `edit_file("probos/...")` reached the running package; now it is refused, as BF-943 already refuses documents for that loop. Build worktrees default to `<repo>.parent/ProbOS-builders` (`worktree_manager.py:44`), outside the package, and the build's file blocks are applied there through `builder_write_refusal` (`test_bf943...:205-209`, T3), so a build in its worktree is unchanged (L6) |
| D11 | What an agent sees | Package and `.env` cases (a): `Captain document write refused (BF-943, BF-975): '<path>' is in the running vessel's code (the probos package directory) or is a .env file it loads at start, which an agent does not write; code and its environment change through a build the Captain reviews`. Writer-root `.env` (b): BF-943's text, which now names environment files too. write_file and edit_file give either text after `write_file refused: ` or `edit_file refused: ` (D14). The log reason code stays `captain_document_refused` at every site |
| D12 | Persisted state, config, flags | No config field. The search `max_files\|list_files` in `config.py`, `config_models/` and `config/` gives 1 line, `config_models/experience.py:318`: a description string that names `list_files` among tools, not a field. This batch edits no facade baseline, config reference or profile, and persists nothing. The rule's changes are new refusals and BF-943's reworded text (P2b-2) |
| D13 | Order | M1 holds both issues' tests as strict xfail. M2a builds #1803 (four source files) and adds `"#1803"` to `_BUILT`. M2b builds #1806 (`builder_paths.py` only) and adds `"#1806"`. M3 does the trackers. M2a edits `swe_harness/tools.py` for #1803; #1806's design adds no call there, and R2 marks the documents rule's refusal at its two sites there (D14). Each milestone is green on its own |
| D14 | The refusal mark (review round 1) | A `ToolResult.error` that starts with the tool's own id and ` refused: ` is its policy answering, and both detectors skip it (`tools/protocol.py:99-115`; `fault_report.py:401`, `fault_detection.py:296`). write_file and edit_file returned the documents rule's text unmarked (`tools.py:1101-1104` and `:1198-1201` at `ecec9031`). Two identical refusals in one run were therefore a same-run defect, counted at `fault_detection.py:308-309` before the noise filter at `:312-317`, and the cross-turn lane took the text as category `other`. The base did this for documents; D10 makes the refusal reachable by a build model's relative `probos/...` path. Both sites now return `f"write_file refused: {refused}"` or `f"edit_file refused: {refused}"`, written as a literal like `read_file`'s (`:472`) and `list_files`'s (`:621`). The rule's text follows the mark unchanged, and the substring checks listed in section 4 still hold. The AD-1344 and BF-911 refusals at the same sites stay unmarked (L9). Rejected: marking all three refusals (that changes two shipped refusals the finding did not name; L9). Also rejected: marking inside the rule (six of its eight callers are not tools and have no tool id) |

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`, run from the worktree root with `PYTHONPATH` set to the worktree's `src` (D6), always with `-n 0 -p no:randomly`.

- **M0:** record the `--collect-only -q` counts for every existing file in G2a and G2b.
- **G1 (M1):** `PY -m pytest tests/test_search_threads_and_running_code.py -q -n 0 -p no:randomly`.
  - Measured 2026-11-16 (Windows, a volume that makes no 8.3 names): **8 passed, 1 skipped, 35 xfailed in 44.6 s**. The skip is R8 (see the header). The four probe cases (S1, S2[python], S2[rg], S3) each wait up to 10 s on the base by design (D5).
  - Then set `SEARCH_AND_RUNNING_CODE_RUNXFAIL=1` and run the file alone. Measured: **35 failed, 8 passed, 1 skipped** (R8). Each failure is an `AssertionError` at an `assert` line of its own test (lines 133, 172, 191, 203, 228, 256, 267, 281, 294, 307, 326, 336, 347, 377, 386, 393, 438 of the new file); none is at an import, a fixture or a call. An XPASS is a FAIL.
- **G2a (M2a):** the new file, then:
  - `test_bf944_pool_agents_read_policy.py`, `test_bf908_floor_and_children.py`, `test_bf948_list_files_read_policy.py`, `test_bf953_read_floor_spellings.py`, `test_bf758_file_read_confinement.py`, `test_bf895_rg_line_parse.py`;
  - `test_ad989_code_search.py`, `test_ad990_file_walk.py`, `test_expansion_agents.py`, `test_ad544_native_tools.py`, `test_ad1179_tool_schema_golden.py`, `test_ad1152_agentic_correlation.py`, `test_ad1240_workspace_results.py`, `test_ad1316_real_effect_routes.py`;
  - `test_ad1346_admission_effect_census.py`, `test_ad1346_admission_sink_wiring.py`, `test_ad1346_admission_file_write_census.py`, `test_ad1346_admission_service.py`, `test_bf892_spawn_env_guard.py`;
  - `test_ad1025b_path_anchoring.py`, `test_ad1200_repository_instructions.py`, `test_ad1200_instruction_file_access.py`, `test_ad1356_s2_tool_effect_table.py`, `test_ad1356_s1_recovery_reads.py`;
  - `test_agent_tiers.py`, `test_prompt_builder.py`, `test_ad983a_capability_affordances.py`, `test_ad152_regressions.py`, `test_layer_boundaries.py`, `test_bf925_guard_names.py`.
  - Measured 2026-11-16 (same host): the new file **14 passed, 29 xfailed, 1 skipped** (R8), 0 failed; the other 30 files **1246 passed, 27 skipped** in total at the base and at M2a, the same at both.
- **G2b (M2b):** the new file, then:
  - `test_bf943_captain_document_write_refusal.py`, `test_ad1344_constitution_write_refusal.py`, `test_bf911_protected_config_write_refusal.py`, `test_ad548_blocked_paths_policy.py`, `test_bf894_builder_write_boundary.py`;
  - `test_file_writer.py`, `test_note_taker_save.py`, `test_office_agents.py`, `test_ad838_office_create_wiring.py`, `test_ad1284_consensus_gate_reachability.py`, `test_ad481_extensions.py`;
  - `test_ad1346_admission_file_write_census.py`, `test_ad1346_admission_store_census.py`, `test_ad544_native_tools.py`, `test_ad1316_real_effect_routes.py`, `test_layer_boundaries.py`, `test_bf925_guard_names.py`;
  - then `PY -P scripts/check_architecture_principles.py --check`.
  - Measured 2026-11-16 (same host): the new file **43 passed, 1 skipped** (R8); the other 17 files **1128 passed, 7 skipped** in total at the base and at M2b, the same at both; `check_architecture_principles.py --check` passes.
- **G3 (M3):** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. No AD or BF number moves; a changed number row is a hard stop.

**Orchestrator:** the oracle, the mutation campaign (section 7), then once: `PY scripts/run_test_gate.py --label search-threads-running-code --receipt logs/gates/search-threads-running-code.receipt.json`.

**Harness rule.** No source change to make a test pass, no new skip, no loosened assertion. If a count differs, stop and report to the Architect.

**Consumer search (run 2026-11-16 on `2b7cb330`; Grep over `tests/`, `tests/fixtures/`, `ui/` and `scripts/`).**

| Search | Hits that matter | Action |
|---|---|---|
| `ReadFloor`, `_ReadFloor`, `_within_floor`, `_search_python`, `_search_rg` | `test_bf908...`: the pattern `ReadFloor\|_ReadFloor\|_within_floor\|_search_python\|_search_rg` gives 19 lines (20 occurrences) in `tests/test_bf908_floor_and_children.py` (2026-11-16). `:587-595` patch both engines on the class (sync `_python`, async `_rg`). `:638` and `:757` pin `roots_built`/`decisions` counts. `:674`. `:692-716` pins the floor build order `["_AllowAll", "_ReadFloor"]`. `:791` and `:806` require `raised.value is injected`. `test_bf895...:186-226` call `_search_rg` (awaited) and `_search_python` (sync) directly | Both stay as they are (sync and async); floors are built in the same order and count; `to_thread` passes the same exception object through. In G2a |
| `create_subprocess_exec` patched, `_Finished` | `test_ad1346_admission_sink_wiring.py:186`, `:214`; `test_ad1346_admission_effect_census.py:380`, `:389`; `test_bf895...:87` | The subprocess and `check_at` stay in `_search_rg` on the loop. In G2a |
| Census rows naming these files | `fixtures/ad1346_effect_census.py:117` and `test_bf892_spawn_env_guard.py:86` (`CodeSearchAgent._search_rg`: one sink); `fixtures/ad1346_file_write_census.py:202`, `:227` (write points only) | No sink and no write point added. In G2a/G2b |
| `resolve_read_path` patched | `test_bf948...:221` (on `swe_tools`; the base call stays on the loop), `test_bf944...:347` (on `file_access`, raises `OSError` inside `ReadFloor.permits`), `test_ad1200_repository_instructions.py:201`, `test_ad1200_instruction_file_access.py:353` | Looked up at call time in the thread. In G2a |
| `inspect.getsource` / text scans | `test_bf758...:326` (the class source of `FileSearchAgent`/`CodeSearchAgent` holds `resolve_for_runtime`): kept in both. `test_bf943...:539-545` (no Windows-only `stat` name in `builder_paths.py`, `tools.py`, `file_writer.py`, `skill_framework.py`): none added | In G2a/G2b |
| `list_files` output and schema | `test_bf948...:208` (exact `{"files": [...]}`); goldens `ad1179...:37`, `ad1152...:845` (description and input schema) | Unchanged shape when not truncated |
| `captain_document_write_refusal`, `CAPTAIN_DOCUMENT_PATHS`, `_document_parts`, `_document_locations`, `_names_a_document` | `test_bf943...:59-64` (eight callers, unchanged), `:583` (`_document_parts`, unchanged), `:649-674` (stage injections: the new checks call no `Path.resolve`, `os.stat` or `os.scandir`), `:260` (no script names the rule); `test_ad1344...:540`, `:581`, `:630`, `:721` (comments) | No list contents or refusal text pinned. In G2b |
| `write_file`, `edit_file`, `commit_write`, `docx_create`, `output_path` on a `probos/` path | 0 lines for the two searches in Absence Verified (reproduced on `e0843f4f`) | Nothing to change |
| `.env` in tests | `test_ad548...:24-27` (hook), `test_bf894...:86` (builder rule), `test_ad808_migration.py:35` (direct write), `test_dotenv.py:44` | The cited lines call the AD-548 hook, the builder rule, a direct write and dotenv; this batch edits none of them |
| `asyncio.to_thread` patched | `test_ad818a*`: `episodic` only | None |
| `_RESERVED`, `is_reserved_device_name` | `test_note_taker_save.py` | Untouched; in G2b |
| `ui/`: tests that spawn Python | `ui/e2e/live-tool-progress.spec.ts:36`, `ui/e2e/consulted-evidence.spec.ts:5`, `ui/playwright.approval-ui.config.ts:55`, `ui/src/...ApprovalWave.test.tsx:725`, `ui/src/__tests__/helpers/issue1375Bridge.ts:3` and `consultedEvidenceBridge.ts:2` | The ui sources name four fixtures (`tests/fixtures/ad1174_progress_bridge.py`, `approval_ui_bridge.py`, `consulted_evidence_bridge.py`, `issue1375_work_state_bridge.py`). They name no changed module or tool (Absence Verified: 0 lines). Three of their lines import `swe_harness.tool_call` or `swe_harness.agentic_loop`, and `swe_harness/tool_call.py:20` imports `swe_harness.tools`, so these fixtures load the `tools.py` that M2a changes. No change to them |
| The write_file/edit_file refusal text (D14, R2) | Run on `ecec9031`, before R2. Readers of the mark: `is_caller_input_error` at `fault_report.py:401` and `fault_detection.py:296`, the only two calls in `src`. Readers of the error's start: the pattern `["'](write_file\|edit_file) (failed\|refused)` gives 2 lines in `src` (the failure texts at `tools.py:1142` and `:1271`) and, in `tests`, `test_bf911...:644-645` (the failure texts). Refusal checks in tests are substrings: `test_bf943...:120`, `:725`, `:740`, `:749`, `:760`, `:774`; `test_ad1344...:469`; this file's cases R2 to R4. `effect_broker.py:920-928` reads only whether an error is present. The model sees the marked text through `ToolCallResult.from_tool_result` | The mark goes before the text, and nothing that reads the text changes. In G-R2 |

## 5. Commit messages

Every body ends with its `Refs` paragraph, followed by the committing agent's trailer paragraph. No subject contains an `AD-` or `BF-` token. No message uses close, fix or resolve in any form, including inside a compound word, a hyphenated word or a quotation, so no message may name `resolve_read_path`. Write "refuses" or "is denied".
- Contract (the orchestrator's): `Search threads and running code (#1803, #1806): contract for searches off the event loop and the running package write refusal`, then `Refs #1803, #1806.`
- M1: `Search threads and running code M1: tests for searches off the event loop and refused writes to the running package, xfail until built (#1803, #1806)`, then `Refs #1803, #1806.`
- M2a: `Search threads and running code M2a: file search, code search and list_files ask the read policy in a worker thread, and list_files stops at a cap (#1803)`, then one paragraph from D1 to D4, then `Refs #1803.`
- M2b: `Search threads and running code M2b: agent writers are denied the running package and the .env files it loads at start (#1806)`, then this paragraph as written, then `Refs #1806.`:
  `The documents rule in builder_paths gains one predicate, _names_running_code, judged on the path as written and on the path after links are followed, in the try block that already judges both forms. It refuses a path at or below the running package directory, taken from the module's own location, and a .env file in that directory or in a directory above it, where load_dotenv() looks at start; .env also joins CAPTAIN_DOCUMENT_PATHS, so a writer's own root holds it. Both sides are compared by the rule's canonical parts. The eight writer sites, their reason code and their log lines are unchanged.`
  Do not paraphrase D6 to D11 into a message: their wording uses the banned verb's past participle.
- M3: `Search threads and running code M3: trackers and ledger (#1803, #1806)`, then `Refs #1803, #1806.`
- R2: `Search threads and running code R2: write_file and edit_file mark the documents rule's refusal as the policy's answer (#1803, #1806)`, then this paragraph as written, then `Refs #1803, #1806.`:
  `write_file and edit_file gave the documents rule's refusal without their refusal mark, so two identical refusals in one run counted as a tool defect, and a build model now meets that refusal when its write_file or edit_file call names the running package. Both now answer write_file refused: or edit_file refused: before the rule's unchanged text. The constitution and protected-configuration refusals at the same two tools stay as they were and are recorded. A new case drives both tools into both fault detectors beside a genuine failure. The contract now orders code search's two worker calls after the subprocess, and the new test's loop probe uses create_task.`

With `BASE` = the `origin/main` commit the batch is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

The orchestrator closes both issues after the gate.

## 6. Recorded limits

- **L1.** A cancelled search's worker runs to the end of its walk. File search with `include_ignored=true` uses an unbounded `rglob`, as on the base, where the same walk held the loop.
- **L2.** Searches share Python's default executor with the other `src` calls into it. The pattern `asyncio\.to_thread|\bto_thread\(|run_in_executor\(None` gives 109 lines in 46 `src` files on the base (orchestrator, 2026-11-16). Many concurrent broad searches can queue other `to_thread` work, but the loop stays live.
- **L3.** `code_search._ReadFloor(None)` does not warn. Production pools pass a runtime (#1803). Considered, deferred: building it on `ReadFloor`.
- **L4.** An existing hard link outside the package to a package file is not refused. Scanning the package on each multi-link write would stat the package's files on each such write and race with `.pyc` writes.
- **L5.** Under a debugger, interactive or frozen start, `find_dotenv` starts at the working directory. That directory's `.env` is refused (D7 b); the directories above it are not.
- **L6.** The native build loop's write_file and edit_file are denied a path at or below the running package, as written or after links are followed (D10); L4 and L7 apply to them.
- **L7.** A share or device spelling of the package is not compared by identity, as with the documents. `self_improvement/versioning.py` (BF-937) and `run_command` are outside the rule.
- **L8.** A truncated listing says that at least one more match exists, not how many.
- **L9.** write_file and edit_file still give the constitution refusal (AD-1344) and the protected-configuration refusal (BF-911) without their refusal mark, as on the base (`tools.py:1097-1100`, `:1105-1108`, `:1194-1197`, `:1202-1205`), so two identical such refusals in one run still count as a tool defect (orchestrator, 2026-11-16: two identical results of the real `write_file`, one for the constitution file `config/standing_orders/federation.md` by its absolute path and one for `credential_vault.json`, each fed to `detect_tool_defect` and `collect_tool_fault_batch`, gave a defect and a same-run defect on the base and on `ecec9031`). The constitution file is named at `standing_orders.py:110-111` and BF-911's credential file names are at `file_access.py:74-77`. Recorded for the wave's follow-up issue.

## 7. The contract

The SEARCH text is LF and ASCII. It starts at a line start and matches once in its file, after the earlier blocks for that file have been applied in label order. Measured 2026-11-16 on `e0843f4f`: the 23 pairs and the new file applied by tool, 0 failures, no anchored copy needed.

### M1

**N1-1.** New file `tests/test_search_threads_and_running_code.py`. Its imports exist on the base: G1 with `SEARCH_AND_RUNNING_CODE_RUNXFAIL=1` measured no failure at an import.

```python
"""Searches off the event loop (#1803) and agent writers kept out of the running vessel's code (#1806).

#1803: file search, code search (both engines) and list_files ask the read policy about each match in a worker thread, so a
broad search does not hold the event loop; list_files stops after a cap of glob matches and says so; a read policy composed
with no runtime warns once per process. #1806: the Captain's documents rule, at all eight writer sites, also refuses a path
at or below the running package directory, as written or once resolved, and a .env file that load_dotenv() can read.
write_file and edit_file give that refusal after their own refusal mark, which neither fault detector counts (R14).

Loop liveness (S1 to S3): the policy check is wrapped by ``_LoopProbe``. Every call records whether it ran on the event
loop's thread; the first call also waits on a threading.Event that only a coroutine on the loop sets. On a worker thread
the wait ends at the next tick; on the loop's own thread that coroutine cannot run, so the wait reaches ``_WAIT_S`` and
the case fails at its assert. No case asserts on a duration.
Writes (R3 to R14): a temporary package stands in for the running one (``builder_paths._RUNNING_PACKAGE``,
``swe_tools._PROJECT_ROOT`` and the standing-orders directory point into it), so the base tree writes into the temporary
tree only. R0 to R2 read the real package and write nothing on either tree.
A case marked ``until_built("#N")`` fails on the base at its own assert; the milestone that builds #N adds it to
``_BUILT``. ``SEARCH_AND_RUNNING_CODE_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos
from probos.agents import code_search
from probos.agents.code_search import CodeSearchAgent
from probos.agents.file_search import FileSearchAgent
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.agentic_dispatch import classify_tool_fault_error
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.cognitive.swe_harness.tools import EditFileTool, ListFilesTool, WriteFileTool
from probos.fault_detection import collect_tool_fault_batch
from probos.fault_report import detect_tool_defect
from probos.security import file_access
from probos.tools.protocol import is_caller_input_error
from tests.test_ad1344_constitution_write_refusal import _dir_link
from tests.test_bf943_captain_document_write_refusal import _call, _office_file, _tree

_BUILT: frozenset[str] = frozenset()


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("SEARCH_AND_RUNNING_CODE_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_WAIT_S = 10.0  # a ceiling only a check on the loop's own thread reaches; a worker's wait ends at the next tick
_TICK_S = 0.005
_TOKEN = "search-threads-needle"
_FILES = 40
_rule = builder_paths.captain_document_write_refusal
_ABSENT_TEXT = "a text that builder_paths.py does not hold: 7d1c0e58"
_GENERAL = ("write_file", "edit_file", "commit", "propose", "docx_create", "pptx_create")


def _on_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _LoopProbe:
    """The slow filter's partner (module docstring)."""

    def __init__(self) -> None:
        self.on_loop: list[bool] = []
        self.answered: list[bool] = []
        self._pending: list[threading.Event] = []

    def call(self) -> None:
        self.on_loop.append(_on_loop())
        if self._pending:
            return
        event = threading.Event()
        self._pending.append(event)
        self.answered.append(event.wait(_WAIT_S))

    async def run(self, awaitable: Any) -> Any:
        task = asyncio.create_task(awaitable)
        while not task.done():
            for event in list(self._pending):
                event.set()
            await asyncio.sleep(_TICK_S)
        return task.result()


def _runtime(tmp: Path) -> SimpleNamespace:
    """What the read policy reads: a data directory (the floor), the agent workspace under it, and no read_roots."""
    data = tmp / "data"
    (data / "workspaces").mkdir(parents=True)
    return SimpleNamespace(
        data_dir=data,
        config_path=None,
        config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]),
            execution=SimpleNamespace(workspace_root=str(data / "workspaces")),
        ),
    )


def _project(tmp: Path, count: int = _FILES) -> Path:
    root = tmp / "project"
    root.mkdir()
    for index in range(count):
        (root / f"note-{index:02d}.txt").write_text(f"{_TOKEN} {index}\n", encoding="utf-8")
    return root


# --- #1803 ---------------------------------------------------------------------------------------------------------


@until_built("#1803")
async def test_s1_file_search_asks_the_policy_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S1 (kills N1)."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = file_access.ReadFloor.permits

    def permits(self: Any, path: str) -> bool:
        probe.call()
        return real(self, path)

    monkeypatch.setattr(file_access.ReadFloor, "permits", permits)
    result = await probe.run(FileSearchAgent(agent_id="s1", runtime=rt)._search_files(str(root), "*.txt"))
    assert result["success"] is True and result["count"] == _FILES, result  # control: the policy admits every file
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_s2_code_search_asks_the_policy_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    """S2 (python kills N2; rg kills N3 and N4): the engine's checks and the final check."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = code_search._ReadFloor.permits

    def permits(self: Any, path: str) -> bool:
        probe.call()
        return real(self, path)

    monkeypatch.setattr(code_search._ReadFloor, "permits", permits)
    if engine == "python":
        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
    else:
        stdout = "".join(f"{path}\x001:{_TOKEN}\n" for path in sorted(root.iterdir())).encode("utf-8")

        class _Rg:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return stdout, b""

        async def spawn(*_args: object, **_kwargs: object) -> _Rg:
            return _Rg()

        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg-stub")
        monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", spawn)
    agent = CodeSearchAgent(agent_id=f"s2-{engine}", runtime=rt)
    plan = await agent.decide({"params": {"path": str(root), "pattern": _TOKEN}})
    result = await probe.run(agent.act(plan))
    assert (result["engine"], result["count"]) == (engine, _FILES), result
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
async def test_s3_list_files_asks_the_policy_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S3 (kills N5): each match's check; the base path's one check (``relative_base``) stays on the loop."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = swe_tools.resolve_read_path

    def resolve(raw: str, **kwargs: Any) -> Path:
        if "relative_base" not in kwargs:
            probe.call()
        return real(raw, **kwargs)

    monkeypatch.setattr(swe_tools, "resolve_read_path", resolve)
    result = await probe.run(ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)}))
    assert result.success and len(result.output["files"]) == _FILES, result
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
async def test_s4_list_files_stops_at_the_cap_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S4 (kills N6): six matches, a cap of five."""
    tmp = tmp_path.resolve()
    root, rt = _project(tmp, count=6), _runtime(tmp)
    monkeypatch.setattr(swe_tools, "_LIST_FILES_MAX_MATCHES", 5, raising=False)  # raising=False: the base has none
    result = await ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)})
    assert result.success, result
    assert len(result.output["files"]) == 5 and result.output.get("truncated") is True, result.output
    note = result.output.get("note", "")
    assert "5 matches" in note and "at least one more" in note, note


async def test_s4_control_a_listing_at_the_cap_is_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: exactly the cap is not truncated, and the output keeps its one key."""
    tmp = tmp_path.resolve()
    root, rt = _project(tmp, count=5), _runtime(tmp)
    monkeypatch.setattr(swe_tools, "_LIST_FILES_MAX_MATCHES", 5, raising=False)
    result = await ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)})
    assert set(result.output) == {"files"} and len(result.output["files"]) == 5, result.output


@until_built("#1803")
async def test_s5_a_read_policy_with_no_runtime_warns_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """S5 (kills N7 and N8): one floor with a runtime (no warning), one with none on a worker thread, one on the loop."""
    monkeypatch.setattr(file_access, "_NO_RUNTIME_WARNED", False, raising=False)
    caplog.set_level(logging.WARNING, logger=file_access.logger.name)
    file_access.ReadFloor(_runtime(tmp_path.resolve()))
    await asyncio.to_thread(file_access.ReadFloor, None)
    file_access.ReadFloor(None)
    warned = [r.getMessage() for r in caplog.records if "operator read_roots not applied" in r.getMessage()]
    assert len(warned) == 1, warned


# --- #1806 ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def vessel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A checkout-shaped tree whose ``src/probos`` stands in for the running package; the working directory is a sibling."""
    tmp = tmp_path.resolve()
    root, work = tmp / "vessel", tmp / "work"
    package = root / "src" / "probos"
    for rel in ("security/file_access.py", "cognitive/builder_paths.py"):
        (package / rel).parent.mkdir(parents=True, exist_ok=True)
        (package / rel).write_text("x v1\n", encoding="utf-8")
    (root / "config" / "standing_orders").mkdir(parents=True)
    (root / "docs").mkdir()
    work.mkdir()
    monkeypatch.setattr(builder_paths, "_RUNNING_PACKAGE", package, raising=False)  # raising=False: the base has none
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", root / "config" / "standing_orders")
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", root / "src")
    monkeypatch.chdir(work)
    return SimpleNamespace(root=root, package=package, work=work)


@until_built("#1806")
def test_r0_the_rule_reads_the_package_this_process_imported() -> None:
    """R0: the guarded directory is ``Path(probos.__file__).resolve().parent``."""
    assert getattr(builder_paths, "_RUNNING_PACKAGE", None) == Path(probos.__file__).resolve().parent


@until_built("#1806")
@pytest.mark.parametrize("given", ["probos/security/x.py", "probos/cognitive/builder_paths.py", "absolute"])
def test_r1_the_rule_refuses_the_real_running_package(given: str) -> None:
    """R1 (kills W1): write_file's relative forms at the real ``<checkout>/src``, and the rule module's absolute path."""
    package = Path(probos.__file__).resolve().parent
    assert swe_tools._PROJECT_ROOT.resolve() == package.parent, "premise: write_file roots a relative path at src"
    text = str(package / "cognitive" / "builder_paths.py") if given == "absolute" else given
    reason = _rule(text, swe_tools._PROJECT_ROOT)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
async def test_r2_edit_file_refuses_the_rules_own_module_with_its_reason_code(caplog: pytest.LogCaptureFixture) -> None:
    """R2 (kills W1): the real tool and module; the text to replace is not in that module (the premise assert), so the base edit replaces nothing and writes nothing."""
    module = Path(builder_paths.__file__).resolve()
    before = module.read_bytes()
    assert _ABSENT_TEXT.encode("utf-8") not in before, "premise: the base edit replaces nothing"
    caplog.set_level(logging.WARNING, logger=swe_tools.logger.name)
    result = await EditFileTool(SimpleNamespace()).invoke(
        {"path": "probos/cognitive/builder_paths.py", "old_text": _ABSENT_TEXT, "new_text": "AMENDED"},
    )
    assert module.read_bytes() == before
    assert not result.success and "BF-975" in (result.error or ""), result
    assert "BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused" in caplog.text


@until_built("#1806")
@pytest.mark.parametrize("writer", _GENERAL)
async def test_r3_each_writer_refuses_a_file_in_the_running_package(vessel: SimpleNamespace, writer: str) -> None:
    """R3 (kills W1): six of the eight sites by absolute path; write_file and edit_file by their relative form too."""
    target = vessel.package / "security" / "file_access.py"
    given = [str(target)] + (["probos/security/file_access.py"] if writer in ("write_file", "edit_file") else [])
    before = _tree(vessel.root)
    for path in given:
        written, error = await _call(writer, path)
        assert not written and "BF-975" in error, (path, error)
    assert _tree(vessel.root) == before


@until_built("#1806")
@pytest.mark.parametrize("writer", ["docx_revise", "xlsx_update"])
async def test_r4_the_office_revise_and_update_refuse_a_file_in_the_running_package(
    vessel: SimpleNamespace, writer: str,
) -> None:
    """R4 (kills W1): the other two sites."""
    target = _office_file(vessel.package / ("x.docx" if writer == "docx_revise" else "x.xlsx"))
    before = target.read_bytes()
    written, error = await _call(writer, str(target))
    assert not written and "BF-975" in error, error
    assert target.read_bytes() == before


_SPELLINGS: dict[str, Any] = {
    "upper-case": lambda p: str(p / "security" / "x.py").upper(),
    "trailing-dot": lambda p: str(p.parent / "probos." / "x.py"),
    "stream": lambda p: str(p / "security" / "x.py") + ":hidden",
    "dot-dot": lambda p: str(p.parent.parent / "docs" / ".." / "src" / "probos" / "x.py"),
}
if os.name == "nt":
    _SPELLINGS["extended-length"] = lambda p: "\\\\?\\" + str(p / "x.py")


@until_built("#1806")
@pytest.mark.parametrize("spelling", sorted(_SPELLINGS))
def test_r5_the_rule_refuses_the_package_in_every_spelling(vessel: SimpleNamespace, spelling: str) -> None:
    """R5 (kills W1)."""
    reason = _rule(_SPELLINGS[spelling](vessel.package), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
def test_r6_a_link_into_the_package_is_refused_once_resolved(vessel: SimpleNamespace) -> None:
    """R6 (kills W4): a junction (Windows) or symlink outside the package, to it."""
    door = vessel.root.parent / "door"
    _dir_link(door, vessel.package)
    assert os.path.samefile(door / "security" / "file_access.py", vessel.package / "security" / "file_access.py"), "premise"
    reason = _rule(str(door / "security" / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
def test_r7_a_link_inside_the_package_is_refused_as_written(vessel: SimpleNamespace) -> None:
    """R7 (kills W5): a link in the package to a directory outside it; only the written form is in the package."""
    outside = vessel.root.parent / "outside"
    outside.mkdir()
    _dir_link(vessel.package / "door", outside)
    assert os.path.samefile(vessel.package / "door", outside), "premise"
    reason = _rule(str(vessel.package / "door" / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
@pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Windows form")
def test_r8_a_real_8_3_alias_of_the_package_is_refused(vessel: SimpleNamespace) -> None:
    """R8: only on a volume that makes short names."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    made = ctypes.windll.kernel32.GetShortPathNameW(str(vessel.package), buffer, 1024)
    if not made or buffer.value.lower() == str(vessel.package).lower():
        pytest.skip("this volume does not make 8.3 names")
    reason = _rule(str(Path(buffer.value) / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


_ENV_PLACES: dict[str, Any] = {
    "package": lambda v: v.package / ".env",
    "src": lambda v: v.package.parent / ".env",
    "checkout": lambda v: v.root / ".env",
}


@until_built("#1806")
@pytest.mark.parametrize("place", sorted(_ENV_PLACES))
async def test_r9_a_dotenv_file_the_loader_can_read_is_refused(vessel: SimpleNamespace, place: str) -> None:
    """R9 (src kills W2): the package directory and the directories above it, where load_dotenv() looks."""
    target = _ENV_PLACES[place](vessel)
    written, error = await _call("commit", str(target))
    assert not written and "BF-943" in error, error
    assert not target.exists()


@until_built("#1806")
@pytest.mark.parametrize("name", [".ENV", ".env.", ".env ", ".env:x"])
def test_r9b_a_dotenv_file_above_the_package_is_refused_in_every_spelling(vessel: SimpleNamespace, name: str) -> None:
    """R9b (kills W2)."""
    reason = _rule(str(vessel.package.parent / name), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
async def test_r10_a_dotenv_file_at_the_writers_root_is_refused(vessel: SimpleNamespace) -> None:
    """R10 (kills W3): the working directory is neither the package nor above it; only the list entry holds it."""
    written, error = await _call("commit", ".env")
    assert not written and "BF-943" in error, error
    assert not (vessel.work / ".env").exists()


_NEIGHBOURS: dict[str, Any] = {
    "dotenv-in-a-subdirectory": lambda v: v.root / "docs" / ".env",
    "dotenv-example": lambda v: v.root / ".env.example",
    "envrc": lambda v: v.root / ".envrc",
    "dotenv-below-the-writers-root": lambda v: v.work / "sub" / ".env",
    "package-name-prefix": lambda v: v.package.parent / "probos_extra" / "x.py",
    "package-name-suffix": lambda v: v.package.parent / "probos.bak" / "x.py",
}


@pytest.mark.parametrize("name", sorted(_NEIGHBOURS))
async def test_r11_control_a_neighbour_of_the_package_or_of_a_dotenv_file_is_written(
    vessel: SimpleNamespace, name: str,
) -> None:
    """Control: these pass on both trees."""
    target = _NEIGHBOURS[name](vessel)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert _rule(str(target), vessel.work) is None
    written, error = await _call("commit", str(target))
    assert written, error


async def test_r12_control_a_tree_shaped_like_a_checkout_outside_the_package_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control (#1806's acceptance): ``tree/src/probos`` outside the running package, written with the working directory in it."""
    tree = tmp_path.resolve() / "tree"
    (tree / "src" / "probos").mkdir(parents=True)
    monkeypatch.chdir(tree)
    assert _rule("src/probos/x.py", tree) is None
    for writer, path in (("commit", "src/probos/x.py"), ("docx_create", "src/probos/report.docx"),
                         ("write_file", str(tree / "src" / "probos" / "y.py"))):
        written, error = await _call(writer, path)
        assert written, (writer, error)
    assert {p.name for p in (tree / "src" / "probos").iterdir()} == {"x.py", "report.docx", "y.py"}


@until_built("#1806")
def test_r13_the_refusal_names_the_running_code_and_the_reviewed_build(vessel: SimpleNamespace) -> None:
    """R13 (kills W1)."""
    reason = _rule(str(vessel.package / "x.py"), vessel.work) or ""
    assert "running vessel's code" in reason and "a build the Captain reviews" in reason, reason


def _outcome(tool_id: str, *results: Any) -> SimpleNamespace:
    """The loop's pairs for *tool_id*'s results, through the adapter it uses (as ``test_bf948...``'s ``_pairs``)."""
    calls = [ToolCallRequest(name=tool_id, arguments={}, id=f"c{n}") for n in range(len(results))]
    pairs = [ToolCallResult.from_tool_result(f"c{n}", result, 0.0) for n, result in enumerate(results)]
    assert all(  # premise: the adapter carries each error verbatim as an error
        pair.is_error is True and pair.output == result.error for pair, result in zip(pairs, results, strict=True)
    )
    return SimpleNamespace(tool_calls=calls, tool_results=pairs)


def _disk_full(*_args: Any, **_kwargs: Any) -> Path:
    raise OSError("disk quota exceeded")


@until_built("#1806")
@pytest.mark.parametrize("given", ["probos/security/file_access.py", ".env", "CODEOWNERS"], ids=["package", "dotenv", "document"])
@pytest.mark.parametrize("tool_id", ["write_file", "edit_file"])
async def test_r14_a_refusal_carries_the_tools_mark_and_is_no_tool_defect(
    vessel: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tool_id: str, given: str,
) -> None:
    """R14 (kills W6, W7): write_file and edit_file answer the documents rule's refusal of a package path, the writer-root
    ``.env`` and a document as ``<tool id> refused: <the rule's text>``. Two identical refusals in one run give neither
    detector a defect; two identical genuine failures of the same tool beside them still do (the premise and the control)."""
    tool = WriteFileTool(SimpleNamespace()) if tool_id == "write_file" else EditFileTool(SimpleNamespace())
    edit = {"content": "AMENDED\n"} if tool_id == "write_file" else {"old_text": "v1", "new_text": "AMENDED"}
    before = _tree(vessel.root)
    refused = [await tool.invoke({"path": given, **edit}) for _ in range(2)]
    assert _tree(vessel.root) == before
    error = refused[0].error or ""
    assert refused[1].error == error, "premise: two identical results"
    assert error.startswith(f"{tool_id} refused: Captain document write refused (BF-943"), error
    assert is_caller_input_error(tool_id, error)
    monkeypatch.setattr(swe_tools, "_resolve_path", _disk_full)
    failed = [await tool.invoke({"path": str(vessel.work / "ok.py"), **edit}) for _ in range(2)]
    assert [r.error for r in failed] == [f"{tool_id} failed: disk quota exceeded"] * 2, "premise: a genuine failure"
    alone = detect_tool_defect(_outcome(tool_id, *failed))
    assert alone is not None and alone.count == 2, "premise: two identical genuine failures are a defect"
    assert detect_tool_defect(_outcome(tool_id, *refused)) is None
    only = collect_tool_fault_batch(_outcome(tool_id, *refused), classify_error=classify_tool_fault_error)
    assert only.tools == () and only.same_run is None, only
    both = _outcome(tool_id, *refused, *failed)
    defect = detect_tool_defect(both)
    assert defect is not None and (defect.tool_id, defect.error_text, defect.count) == (tool_id, failed[0].error, 2)
    batch = collect_tool_fault_batch(both, classify_error=classify_tool_fault_error)
    [evidence] = batch.tools
    assert evidence.defect is not None and evidence.defect.error_text == failed[0].error and evidence.mixed is False
    assert batch.same_run is not None and batch.same_run.error_text == failed[0].error
```

### M2a (#1803)

**P2a-1** (`src/probos/security/file_access.py`: import)
SEARCH:
```
import re
import stat
from collections.abc import Iterable, Iterator, Sequence
```
REPLACE:
```
import re
import stat
import threading
from collections.abc import Iterable, Iterator, Sequence
```

**P2a-2** (`ReadFloor` warns once with no runtime)
SEARCH:
```
class ReadFloor:
    """BF-944: the read policy *runtime* configures (the floor, the agent workspace, ``security_infra.read_roots``), composed once
    as :func:`resolve_for_runtime` composes it, for a caller that decides many paths. Built per listing or search."""

    def __init__(self, runtime: Any) -> None:
        self._protected = protected_read_roots(runtime)
```
REPLACE:
```
# BF-972 (#1803): a ReadFloor composed with no runtime says once per process that operator read_roots are not applied. The
# flag is set under the lock, so a floor built on a worker thread and one built on the loop log once between them; a test
# resets it with ``monkeypatch.setattr(file_access, "_NO_RUNTIME_WARNED", False)``.
_NO_RUNTIME_LOCK = threading.Lock()
_NO_RUNTIME_WARNED = False


def _warn_no_runtime_once() -> None:
    """BF-972 (#1803): log, once per process, that a read policy was composed without a runtime."""
    global _NO_RUNTIME_WARNED
    with _NO_RUNTIME_LOCK:
        if _NO_RUNTIME_WARNED:
            return
        _NO_RUNTIME_WARNED = True
    logger.warning("BF-972: read policy without a runtime; operator read_roots not applied (the floor still applies)")


class ReadFloor:
    """BF-944: the read policy *runtime* configures (the floor, the agent workspace, ``security_infra.read_roots``), composed once
    as :func:`resolve_for_runtime` composes it, for a caller that decides many paths. Built per listing or search.

    BF-972 (#1803): it may be asked from a worker thread. It holds three attributes set here and only read afterwards, and
    each ``permits`` call keeps its state in its own frame."""

    def __init__(self, runtime: Any) -> None:
        if runtime is None:
            _warn_no_runtime_once()  # BF-972 (#1803): the floor applies; operator read_roots cannot be read
        self._protected = protected_read_roots(runtime)
```

**P2a-3** (`src/probos/agents/file_search.py`: import)
SEARCH:
```
import logging
from pathlib import Path
from typing import Any
```
REPLACE:
```
import asyncio
import logging
from pathlib import Path
from typing import Any
```

**P2a-4** (`_search_files`: the floor is imported by the helper)
SEARCH:
```
        from probos.security.file_access import ReadFloor, resolve_for_runtime
```
REPLACE:
```
        from probos.security.file_access import resolve_for_runtime
```

**P2a-5** (the walk, the check and the sort in a worker thread)
SEARCH:
```
            if include_ignored:
                matches = sorted(str(m) for m in p.rglob(pattern))
            else:
                from probos.substrate.file_walk import iter_files
                matches = sorted(
                    str(f) for f in iter_files(p, skip_binary=False)
                    if f.match(pattern)
                )
            # BF-944: a ``..`` pattern or a link under the base can lead out of it, so a match is kept when the read policy admits the
            # path it resolves to and dropped otherwise; the policy is composed after the walk.
            floor = ReadFloor(getattr(self, "_runtime", None))
            kept = [m for m in matches if floor.permits(m)]  # BF-944: a match the policy refuses is left out and not counted
            if len(kept) != len(matches):
                logger.info("BF-944: file search left out %d match(es) the read policy refuses", len(matches) - len(kept))
            matches = kept
```
REPLACE:
```
            # BF-972 (#1803): the walk, the match, the read policy and the sort run in one worker thread, so a broad search
            # does not hold the event loop; the result is as before.
            matches = await asyncio.to_thread(_admitted_matches, p, pattern, include_ignored, getattr(self, "_runtime", None))
```

**P2a-6** (the helper, at the end of the module)
SEARCH:
```
                "count": len(matches),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
```
REPLACE:
```
                "count": len(matches),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _admitted_matches(base: Path, pattern: str, include_ignored: bool, runtime: Any) -> list[str]:
    """BF-972 (#1803): the sorted matches of *pattern* under *base* that the read policy admits; run in a worker thread.

    AD-990: the default walk skips ignored, hidden and default-ignore entries and stops at ``iter_files``'s cap;
    ``include_ignored`` is the raw recursive glob. BF-944: a ``..`` pattern or a link under the base can lead out of it, so
    a match is kept when the read policy admits the path it resolves to; the policy is composed after the walk.
    """
    from probos.security.file_access import ReadFloor

    if include_ignored:
        matches = sorted(str(m) for m in base.rglob(pattern))
    else:
        from probos.substrate.file_walk import iter_files
        matches = sorted(str(f) for f in iter_files(base, skip_binary=False) if f.match(pattern))
    floor = ReadFloor(runtime)
    kept = [m for m in matches if floor.permits(m)]  # BF-944: a match the policy refuses is left out and not counted
    if len(kept) != len(matches):
        logger.info("BF-944: file search left out %d match(es) the read policy refuses", len(matches) - len(kept))
    return kept
```

**P2a-7** (`src/probos/agents/code_search.py`: `act`)
SEARCH:
```
            if rg_result is not None:
                # BF-908 A4: a FRESH floor, built after the engine ran, decides what is returned:
                # the engines' cached allows are not the final authorization (review round 2 of
                # C1b returned a protected line through a link retargeted during the search).
                return _within_floor(rg_result, _ReadFloor(getattr(self, "_runtime", None)))
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root, floor=floor), _ReadFloor(getattr(self, "_runtime", None)))
```
REPLACE:
```
            if rg_result is not None:
                # BF-908 A4: a FRESH floor, built after the engine ran, decides what is returned:
                # the engines' cached allows are not the final authorization (review round 2 of
                # C1b returned a protected line through a link retargeted during the search).
                # BF-972 (#1803): built and asked in a worker thread, off the event loop.
                return await asyncio.to_thread(_final_check, rg_result, getattr(self, "_runtime", None))
            # Tier-2: rg failed -> fall through to the Python engine.
        # BF-972 (#1803): the Python engine and the final check run in one worker thread, off the event loop.
        return await asyncio.to_thread(self._search_python_checked, plan, root, floor)
```

**P2a-8** (`_search_rg`: the parse moves to a worker thread)
SEARCH:
```
        if proc.returncode not in (0, 1):
            return None
        matches: list[dict] = []
        parsed_lines = 0
        # BF-895 (#1548): frame on LF only. str.splitlines() also splits at U+2028, U+2029,
        # U+0085, form feed and others, which a file name or a match can hold: it cut a path
        # short and minted a record from the tail of a match. One trailing CR (a CRLF file's
        # line) is part of the terminator, as splitlines() treated it.
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            parsed = _parse_rg_line(line.removesuffix("\r"))
            if parsed is None:
                continue
            parsed_lines += 1
            # BF-908 A3: skipped before it is counted, so it never uses up max_results.
            if floor is not None and not floor.permits(parsed["path"]):
                continue
            matches.append(parsed)
            if len(matches) >= plan["max_results"]:
                break
        # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
        # and rg disagree: report nothing rather than a false zero, so act() falls back.
        # BF-908 A3: lines that parsed and that the floor refused are not that case.
        if not parsed_lines and (proc.returncode == 0 or stdout):
            logger.warning(
                "BF-895: rg exited %s with %d output bytes but no parsable match under %s; "
                "falling back to the Python engine",
                proc.returncode, len(stdout), root,
            )
            return None
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "rg",
            "truncated": len(matches) >= plan["max_results"],
        }
```
REPLACE:
```
        if proc.returncode not in (0, 1):
            return None
        # BF-972 (#1803): the parse and each line's read-floor check run in one worker thread, off the event loop.
        return await asyncio.to_thread(_rg_result, stdout, proc.returncode, plan, root, floor)
```

**P2a-9** (the Python path's helper, the final check and the moved parse)
SEARCH:
```
            "engine": "python",
            "truncated": truncated,
        }


def _text_lines(fp: Path) -> Iterator[tuple[int, str]]:
```
REPLACE:
```
            "engine": "python",
            "truncated": truncated,
        }

    def _search_python_checked(self, plan: dict, root: Path, floor: _ReadFloor) -> dict:
        """BF-972 (#1803): the Python engine, then BF-908 A4's final check with a fresh floor; run in one worker thread."""
        return _final_check(self._search_python(plan, root, floor=floor), getattr(self, "_runtime", None))


def _final_check(result: dict, runtime: Any) -> dict:
    """BF-972 (#1803): BF-908 A4's final check, a fresh ``_ReadFloor`` built now, after the engine ran; run in a worker thread."""
    return _within_floor(result, _ReadFloor(runtime))


def _rg_result(stdout: bytes, returncode: int, plan: dict, root: Path, floor: _ReadFloor | None) -> dict | None:
    """BF-972 (#1803): rg's output parsed, each line's file asked of *floor*, in a worker thread; ``None`` sends ``act``
    to the Python engine. The body is ``CodeSearchAgent._search_rg``'s, with ``proc.returncode`` passed in as *returncode* (BF-895, BF-908 A3)."""
    matches: list[dict] = []
    parsed_lines = 0
    # BF-895 (#1548): frame on LF only. str.splitlines() also splits at U+2028, U+2029,
    # U+0085, form feed and others, which a file name or a match can hold: it cut a path
    # short and minted a record from the tail of a match. One trailing CR (a CRLF file's
    # line) is part of the terminator, as splitlines() treated it.
    for line in stdout.decode("utf-8", errors="replace").split("\n"):
        parsed = _parse_rg_line(line.removesuffix("\r"))
        if parsed is None:
            continue
        parsed_lines += 1
        # BF-908 A3: skipped before it is counted, so it never uses up max_results.
        if floor is not None and not floor.permits(parsed["path"]):
            continue
        matches.append(parsed)
        if len(matches) >= plan["max_results"]:
            break
    # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
    # and rg disagree: report nothing rather than a false zero, so act() falls back.
    # BF-908 A3: lines that parsed and that the floor refused are not that case.
    if not parsed_lines and (returncode == 0 or stdout):
        logger.warning(
            "BF-895: rg exited %s with %d output bytes but no parsable match under %s; "
            "falling back to the Python engine",
            returncode, len(stdout), root,
        )
        return None
    return {
        "success": True,
        "data": matches,
        "count": len(matches),
        "engine": "rg",
        "truncated": len(matches) >= plan["max_results"],
    }


def _text_lines(fp: Path) -> Iterator[tuple[int, str]]:
```

**P2a-10** (`src/probos/cognitive/swe_harness/tools.py`: import asyncio)
SEARCH:
```
from __future__ import annotations

import ctypes
import hashlib
```
REPLACE:
```
from __future__ import annotations

import asyncio
import ctypes
import hashlib
```

**P2a-11** (the walk cap)
SEARCH:
```
    workspace_exempt_roots,
)
from probos.tools.protocol import (
```
REPLACE:
```
    workspace_exempt_roots,
)
from probos.substrate.file_walk import DEFAULT_MAX_FILES
from probos.tools.protocol import (
```

**P2a-12** (the cap, its note and the worker-thread helper)
SEARCH:
```
    "list_files refused: pattern must be a relative glob with no '..' part; "
    "name the directory in path"
)


class ListFilesTool:
```
REPLACE:
```
    "list_files refused: pattern must be a relative glob with no '..' part; "
    "name the directory in path"
)
# BF-972 (#1803): list_files examines at most this many glob matches (substrate.file_walk's walk cap) and says when more match.
_LIST_FILES_MAX_MATCHES = DEFAULT_MAX_FILES
_LIST_FILES_TRUNCATED = (
    "list_files stopped after examining {limit} matches; at least one more match was not examined. "
    "Narrow the pattern or the path."
)


def _listed_matches(
    base: Path, pattern: str, protected: list[Path], exempt: list[Path], permitted: list[Path] | None,
) -> tuple[list[str], bool]:
    """BF-972 (#1803): what ``list_files`` lists, and whether it stopped at the cap; run in a worker thread.

    At most ``_LIST_FILES_MAX_MATCHES`` glob matches are examined, refused ones included; the result is truncated exactly
    when one more match exists. BF-948's and BF-953's rules for each match, moved here unchanged.
    """
    files: list[str] = []
    for examined, match in enumerate(base.glob(pattern)):
        if examined >= _LIST_FILES_MAX_MATCHES:
            return files, True  # BF-972: a match beyond the cap exists; it and any after it are not examined
        try:
            resolve_read_path(
                str(match), protected_roots=protected, exempt_roots=exempt,
                permitted_roots=permitted,
            )
        except FileAccessDenied:
            continue  # BF-948: refused by the policy, so left out and not counted
        shown = reader_spelling(match)  # BF-953: the spelling the verified reader's rules on the text admit
        if shown is None:
            continue  # BF-953 (Amendments 2 and 3): there is none, so it is left out like a refused match
        files.append(
            str(shown.relative_to(_PROJECT_ROOT))
            if shown.is_relative_to(_PROJECT_ROOT) else str(shown)
        )
    return files, False


class ListFilesTool:
```

**P2a-13** (the `ListFilesTool` docstring)
SEARCH:
```
    say that it opens (BF-953 L18).
    Any other failure is answered and logged with its exception class only.
    """
```
REPLACE:
```
    say that it opens (BF-953 L18).
    BF-972 (#1803): the glob and each match's checks run in one worker thread, and at most
    ``_LIST_FILES_MAX_MATCHES`` matches are examined (refused ones included); when one more
    match exists the output also holds ``truncated: True`` and a ``note`` saying so.
    Any other failure is answered and logged with its exception class only.
    """
```

**P2a-14** (`ListFilesTool.invoke`: the loop goes to the helper)
SEARCH:
```
            files: list[str] = []
            for match in base.glob(pattern):
                try:
                    resolve_read_path(
                        str(match), protected_roots=protected, exempt_roots=exempt,
                        permitted_roots=permitted,
                    )
                except FileAccessDenied:
                    continue  # BF-948: refused by the policy, so left out and not counted
                shown = reader_spelling(match)  # BF-953: the spelling the verified reader's rules on the text admit
                if shown is None:
                    continue  # BF-953 (Amendments 2 and 3): there is none, so it is left out like a refused match
                files.append(
                    str(shown.relative_to(_PROJECT_ROOT))
                    if shown.is_relative_to(_PROJECT_ROOT) else str(shown)
                )
            return ToolResult(output={"files": files})
```
REPLACE:
```
            # BF-972 (#1803): the glob and each match's policy check run in one worker thread, off the event loop.
            files, truncated = await asyncio.to_thread(_listed_matches, base, pattern, protected, exempt, permitted)
            if truncated:  # BF-972: the listing says it stopped, and how to narrow it
                return ToolResult(output={
                    "files": files,
                    "truncated": True,
                    "note": _LIST_FILES_TRUNCATED.format(limit=_LIST_FILES_MAX_MATCHES),
                })
            return ToolResult(output={"files": files})
```

**P2a-15** (`tests/test_search_threads_and_running_code.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset()
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1803"})
```

### M2b (#1806)

**P2b-1** (`src/probos/cognitive/builder_paths.py`: the `.env` entry)
SEARCH:
```
    "CODEOWNERS",
    "docs/CODEOWNERS",
)
```
REPLACE:
```
    "CODEOWNERS",
    "docs/CODEOWNERS",
    ".env",  # BF-975 (#1806): the environment file load_dotenv() reads at start (__main__.py), at a writer's own root
)
```

**P2b-2** (the package directory, the predicate and the refusal text; BF-943's text names environment files too)
SEARCH:
```
        f"Captain document write refused (BF-943): {path_text!r} is one of the Captain's governance, instruction or "
        "manifest files in a checkout (builder_paths.CAPTAIN_DOCUMENT_PATHS), which an agent does not write; standing "
```
REPLACE:
```
        f"Captain document write refused (BF-943): {path_text!r} is one of the Captain's governance, instruction, "
        "manifest or environment files in a checkout (builder_paths.CAPTAIN_DOCUMENT_PATHS), which an agent does not write; standing "
```

**P2b-3** (before `_running_checkout`)
SEARCH:
```
def _running_checkout() -> Path:
    """The project root the running vessel reads its standing orders from: the directory above ``config/standing_orders``."""
```
REPLACE:
```
# BF-975 (#1806): the running vessel's package directory, ``Path(probos.__file__).resolve().parent`` (this module is
# ``probos/cognitive/builder_paths.py``; the new test's R0 pins the equality).
_RUNNING_PACKAGE = Path(__file__).resolve().parents[1]
_DOTENV_KEY = _canonical(".env")


def _running_code_refusal(path_text: str) -> str:
    return (
        f"Captain document write refused (BF-943, BF-975): {path_text!r} is in the running vessel's code (the probos "
        "package directory) or is a .env file it loads at start, which an agent does not write; code and its environment "
        "change through a build the Captain reviews"
    )


def _names_running_code(target: Path) -> bool:
    """BF-975 (#1806): whether absolute *target* is at or below the running package directory, or is a ``.env`` file in it
    or in a directory above it (each place ``load_dotenv()`` looks from ``__main__.py``). Both sides are compared as
    :func:`_names_a_document` compares a root, by :func:`_document_parts` (case, a ``:`` suffix, trailing dots and spaces,
    the extended-length prefix). It calls no filesystem function."""
    parts, top = _document_parts(target), _document_parts(_RUNNING_PACKAGE)
    if parts[: len(top)] == top:
        return True
    return len(parts) >= 2 and parts[-1] == _DOTENV_KEY and parts[:-1] == top[: len(parts) - 1]


def _running_checkout() -> Path:
    """The project root the running vessel reads its standing orders from: the directory above ``config/standing_orders``."""
```

**P2b-4** (the rule's docstring)
SEARCH:
```
    error, not a name taken as written), examining or listing. A document
    in another tree is not refused. Any other exception propagates.
    """
```
REPLACE:
```
    error, not a name taken as written), examining or listing. BF-975 (#1806): also a path that, as written or once
    resolved, lies at or below the running package directory (``_RUNNING_PACKAGE``), or is a ``.env`` file in it or in a
    directory above it (where ``load_dotenv()`` looks). A document in another tree is not refused. Any other exception
    propagates.
    """
```

**P2b-5** (the two checks, in the try block that already judges both forms)
SEARCH:
```
        if _names_a_document(Path(os.path.abspath(target)), [Path(os.path.abspath(r)) for r in roots]):
            return _captain_document_refusal(path)
        resolved_roots = list(dict.fromkeys(_resolve(r) for r in roots))
        resolved = _resolve(target)
        if _names_a_document(resolved, resolved_roots):
            return _captain_document_refusal(path)
```
REPLACE:
```
        if _names_a_document(Path(os.path.abspath(target)), [Path(os.path.abspath(r)) for r in roots]):
            return _captain_document_refusal(path)
        if _names_running_code(Path(os.path.abspath(target))):  # BF-975 (#1806): the running code, as written
            return _running_code_refusal(path)
        resolved_roots = list(dict.fromkeys(_resolve(r) for r in roots))
        resolved = _resolve(target)
        if _names_a_document(resolved, resolved_roots):
            return _captain_document_refusal(path)
        if _names_running_code(resolved):  # BF-975 (#1806): the running code, once resolved (a link into it)
            return _running_code_refusal(path)
```

**P2b-6** (`tests/test_search_threads_and_running_code.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset({"#1803"})
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1803", "#1806"})
```

### R2 (#1806, after review round 1): the refusal mark

This section implements D14. R2's test changes are in N1-1's copy above:
- the added imports;
- a docstring sentence;
- `asyncio.create_task` in `_LoopProbe.run`;
- `_outcome`, `_disk_full` and R14.

The Architect wrote this section against the candidate tree `dca4f150` on 2026-11-16; the orchestrator applied it by tool and measured G-R2 and rows W6 and W7.

**P-R2-1** (`src/probos/cognitive/swe_harness/tools.py`: write_file)
SEARCH:
```
                logger.warning("BF-943 WriteFileTool refused operation=write_file reason_code=captain_document_refused")
                return ToolResult(error=refused)
```
REPLACE:
```
                logger.warning("BF-943 WriteFileTool refused operation=write_file reason_code=captain_document_refused")
                return ToolResult(error=f"write_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it
```

**P-R2-2** (edit_file)
SEARCH:
```
                logger.warning("BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused")
                return ToolResult(error=refused)
```
REPLACE:
```
                logger.warning("BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused")
                return ToolResult(error=f"edit_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it
```

**G-R2:**
- Run with `-n 0 -p no:randomly`: the new file, then `test_bf943_captain_document_write_refusal.py`, `test_ad1344_constitution_write_refusal.py`, `test_bf911_protected_config_write_refusal.py`, `test_bf948_list_files_read_policy.py`, `test_ad1205_fault_paths.py`, `test_ad546_native_builder_harness.py`, `test_ad1356_s2_tool_effect_table.py`, `test_ad544_native_tools.py`, `test_ad1316_real_effect_routes.py`.
- Measured 2026-11-16 (same host as above): the new file at R2 **49 passed, 1 skipped** (R8); the nine other files **1164 passed, 3 skipped** in total at `ecec9031` and at R2, the same at both (the skips are `test_bf943...` on a volume that makes no 8.3 names and two POSIX cases of `test_ad1316...`).
- Then W6 and W7 (7b).

### M3: trackers and ledger

Replace `DATE` with M3's date. No line this milestone adds carries an `AD-` or `BF-` token or this contract's file name; P3-2's anchor heading is an existing line, kept.

**P3-1** (`PROGRESS.md`). The anchor is the title line and the blank line after it; the earlier batches' entries stay below this one.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**File and code search ask the read policy off the event loop, and agent writers are denied the running vessel's code (DATE), #1803 #1806.**
- **Base.** File search, code search and list_files ran their walk and each match's read-policy check inside async handlers, so a broad search held the event loop. list_files had no cap on its glob. The Captain's documents rule refused governance, instruction and manifest files but not the code the vessel runs. write_file roots a relative path at the checkout's src, so a holder could rewrite the package, including the modules that hold the write refusals, and the .env file the vessel loads at start.
- **Change.** Each search runs its walk, policy checks and sort in a worker thread; code search with rg parses in one and runs its final check in another. What the policy admits is unchanged. list_files examines at most 20,000 glob matches and, when more match, says so in `truncated` and `note`. A read policy built with no runtime logs once per process that operator read_roots are not applied. At all eight writer sites the documents rule also refuses a path at or below the running package directory, as written or after links are followed, and a .env file in that directory or in any directory above it, where the start-up loader looks. `.env` is also in the documents list, so a writer's own root holds it. Builds in their worktrees are unchanged. The native build loop's write_file and edit_file are denied a path at or below the running package, as written or after links are followed. write_file and edit_file give that refusal, like the documents refusal, after their own refusal mark, so neither fault detector counts a refused write as a broken tool; their constitution and protected-configuration refusals are unchanged and recorded. Refs #1803, #1806.

```

**P3-2** (`DECISIONS.md`). The anchor is the heading below, found by its text: `DECISIONS.md` changed between `2b7cb330` and `e0843f4f`, so no line number is given. The earlier batches insert before it too.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### File and code search off the event loop; agent writers kept out of the running vessel's code (DATE, #1803, #1806)

- *Scope.* `security/file_access.py`, `agents/file_search.py`, `agents/code_search.py`, `cognitive/swe_harness/tools.py` (list_files), `cognitive/builder_paths.py`; one new test file.
- *G1 (search).* Each search's walk and policy checks move into `asyncio.to_thread`; the policy is unchanged, and admission's subprocess check stays on the loop. A cancelled search's worker runs to the end of its walk. Rejected: a semaphore or a dedicated executor (a primitive shared across event loops, or a pool to shut down).
- *G2 (list cap).* At most 20,000 matches are examined, refused ones included; `truncated` and `note` appear only when one more match exists, so an untruncated listing keeps its shape.
- *G3 (running code).* The package directory is the running module's own; it is compared by the rule's canonical parts, as written and after links are followed. A `.env` file is refused where the start-up loader looks (the package directory and every directory above it) and, as a documents entry, at the writer's root. Rejected: `src/` as an entry (it would refuse a user's own working-directory `src`), and protecting only the rule's modules. Deferred: second names (hard links) of a package file. write_file and edit_file give the rule's refusal after their own refusal mark (`write_file refused: `), so neither fault detector counts it as a tool defect; their constitution and protected-configuration refusals stay unmarked (L9).
- *Rollout.* No flag; the rule adds refusals and rewords the Captain's documents rule's refusal text to name environment files. *Residual.* L1 to L9 of the contract. *Reversal.* Revert the batch's commits in reverse order.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. No AD or BF number moves. The roadmap Bug Tracker is not edited (the batch-4 precedent).

## 7b. Mutation rows (measured 2026-11-16 by the orchestrator on the new file alone, base `e0843f4f`, Windows, no 8.3 names: each original line occurs once in its file, each row is killed by the cases shown, and no row survives)

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| N1 | `file_search.py` | `matches = await asyncio.to_thread(_admitted_matches, p, pattern, include_ignored, getattr(self, "_runtime", None))` | `matches = _admitted_matches(p, pattern, include_ignored, getattr(self, "_runtime", None))` | S1 |
| N2 | `code_search.py` | `return await asyncio.to_thread(self._search_python_checked, plan, root, floor)` | `return self._search_python_checked(plan, root, floor)` | S2[python] |
| N3 | same | `return await asyncio.to_thread(_rg_result, stdout, proc.returncode, plan, root, floor)` | `return _rg_result(stdout, proc.returncode, plan, root, floor)` | S2[rg] |
| N4 | same | `return await asyncio.to_thread(_final_check, rg_result, getattr(self, "_runtime", None))` | `return _final_check(rg_result, getattr(self, "_runtime", None))` | S2[rg] (`on_loop`) |
| N5 | `tools.py` | `files, truncated = await asyncio.to_thread(_listed_matches, base, pattern, protected, exempt, permitted)` | `files, truncated = _listed_matches(base, pattern, protected, exempt, permitted)` | S3 |
| N6 | same | `if examined >= _LIST_FILES_MAX_MATCHES:` | `if False:` | S4 |
| N7 | `file_access.py` | `if runtime is None:` | `if False:` | S5 (0 records) |
| N8 | same | `if _NO_RUNTIME_WARNED:` | `if False:` | S5 (2 records) |
| W1 | `builder_paths.py` | `if parts[: len(top)] == top:` | `if False:` | R1 (3), R2, R3 (6), R4 (2), R5 (5), R6, R7, R13, R14[write_file-package], R14[edit_file-package]: 22 cases. R6 and R7 also need the prefix check; W4 and W5 each disable one call site. R8 skipped, so it is not in the measured set |
| W2 | same | `return len(parts) >= 2 and parts[-1] == _DOTENV_KEY and parts[:-1] == top[: len(parts) - 1]` | `return False` | R9[src], R9b |
| W3 | same | `".env",  # BF-975 (#1806): the environment file load_dotenv() reads at start (__main__.py), at a writer's own root` | delete the line | R10 |
| W4 | same | `if _names_running_code(resolved):  # BF-975 (#1806): the running code, once resolved (a link into it)` | `if False:` | R6. R8 skipped, so it is not in the measured set |
| W5 | same | `if _names_running_code(Path(os.path.abspath(target))):  # BF-975 (#1806): the running code, as written` | `if False:` | R7 |
| W6 | `tools.py` | `return ToolResult(error=f"write_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it` | `return ToolResult(error=refused)` | R14[write_file-package], R14[write_file-dotenv], R14[write_file-document] (3) |
| W7 | same | `return ToolResult(error=f"edit_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it` | `return ToolResult(error=refused)` | R14[edit_file-package], R14[edit_file-dotenv], R14[edit_file-document] (3) |

In the measured sets, neither W1 nor W2 alone kills R9[package], and neither W2 nor W3 alone kills R9[checkout]: each case is covered by two rules. The campaign runs the new file alone. R2 added W6 and W7 after review round 1, and the orchestrator re-measured all 15 rows at R2 (a scratch tree at `ecec9031` with R2's pairs applied, the same host; 50 cases, 49 passed and 1 skipped unmutated): each original line occurs once, no row survives, and each row is killed by exactly the cases shown; W1's killed set is the earlier 20 cases and R14's two package cases.

## 8. What this does NOT change

- What the read policy admits or refuses; `directory_list`; `resolve_for_runtime`; `code_search._ReadFloor`'s composition and cache.
- The eight writer sites' log lines and reason codes, and six of the sites entirely; write_file and edit_file change only their answer to the documents rule, which gains their refusal mark (D14). `builder_write_refusal`; AD-548's hook; the effect broker's authority; the AD-1344 and BF-911 refusal texts (L9).
- `output_schema`, the description and the input schema of list_files.
- Config, profiles, the facade baseline, the config reference, `ui/` and the commercial overlay. No existing test file is edited.

## 9. Diff Reviewer (`gpt-6.1-sol`): properties to verify

Name the consumer for each property and confirm that it accepts the change.

1. **Same answers.**
   - Every search returns, for any input, what the base returned, except `list_files` past its cap (D3: it stops, and the output gains `truncated` and `note`).
   - Each match's policy check runs on a worker thread: every `permits` call of `ReadFloor` or `code_search._ReadFloor`, and list_files' per-match `resolve_read_path` call. These stay on the loop: the root path's check (`resolve_for_runtime` at `file_search.py:131` and `code_search.py:146` on the base; the `relative_base` call at `tools.py:578` in list_files), the roots list_files composes before its walk, and the floor `act` builds for its engines (`code_search.py:155`), whose construction asks about no path.
   - The rg path's subprocess and `check_at` stay on the loop.
   - **Consumers:** `test_bf908...:638`, `:716` and `:757` (the floor build counts and order); `:791` (the same exception object); `test_bf895...:186-226` (`_search_rg` awaited and `_search_python` sync); `test_ad1346_admission_effect_census.py:389`.
2. **Thread safety (D1).** Verify that a worker thread writes no shared state other than logging, the lock-guarded once-flag and the cache of a `code_search._ReadFloor` that one thread at a time uses.
3. **The cap (D3).**
   - At most `_LIST_FILES_MAX_MATCHES` matches are checked; the next match is drawn from the glob only to learn that it exists.
   - `truncated` appears only when one more exists, and an untruncated output equals `{"files": [...]}`.
   - **Consumer:** `test_bf948...:208`.
4. **The rule (D6 to D8).**
   - `_names_running_code` calls no filesystem function: `_document_parts` and `_canonical` work on the text (`builder_paths.py:83-85`, `:269-278` on the base).
   - It is called on the written and the resolved form inside the existing try block, adding no `Path.resolve`, `os.stat` or `os.scandir` call.
   - All eight sites reach it through the one function.
   - **Consumers:** `test_bf943...:586-693` (stage injections), `:59-64` (the callers census), `:539-545` (the stat-name scan).
5. **No regression for writers.** A path that is not in the package, not a `.env` file the start-up loader reads and not a `.env` file at a writer's root gets the same decision as on the base; a refused document's text now also names environment files (P2b-2). **Consumers:** the neighbour controls of `test_bf943...` (`:183`, `:195`) and R11/R12.
6. **Paperwork.** ASCII text; no `AD-` or `BF-` token in a commit subject or in a tracker line this batch adds; both scans of section 5 are clean.
7. **The refusal mark (D14).**
   - write_file's and edit_file's answer to the documents rule is `<tool id> refused: ` followed by the rule's unchanged text.
   - Their AD-1344 and BF-911 answers and every failure text (`write_file failed:`, `edit_file failed:`, `File not found:`) stay unmarked.
   - Two identical marked refusals in one run give neither detector a defect, while two identical failures beside them still do.
   - **Consumers:** `fault_report.detect_tool_defect` (`:401`); `fault_detection.collect_tool_fault_batch` (`:296`, before `:308-309` and `:312-317`); their feeders `native_builder.py:186-191`, `agentic_dispatch.py:4409` and `:4450`; the model's transcript (`tool_call.py:696`); `effect_broker.py:920-928`; the substring checks in `test_bf943...`, `test_ad1344...` and this file's cases R2 to R4; `test_bf911...:644-645`.

## 10. Acceptance criteria

- **#1803:**
  - S1 to S3 pass, and N1 to N5 each fail their case.
  - The BF-944, BF-908 and BF-948 refusal tests pass unchanged.
  - The list cap holds (S4, with N6 failing it).
  - `ReadFloor(None)` logs once (S5; N7 and N8 each fail it).
- **#1806:**
  - The package refusal:
    - The rule refuses `probos/security/x.py`, `probos/cognitive/builder_paths.py` and the absolute path of the real package's `builder_paths.py`, rooted at the real `<checkout>/src` (R1).
    - edit_file refuses the real `builder_paths.py` and logs `reason_code=captain_document_refused` (R2).
    - write_file and edit_file refuse a file in the stand-in package by its absolute and its relative path (R3).
  - The other writers: commit_write, docx_create and the other sites are refused (R3, R4).
  - `.env` where the loader and the writer's root reach it (R9, R9b, R10).
  - Controls: R11, R12.
  - Mutations: W1 fails the package cases, W2 the `.env` above the package, W3 the writer-root `.env`.
  - The mark (D14): write_file and edit_file answer a package path, the writer-root `.env` and a document with their refusal mark. Two such answers are no tool defect to either detector, while two genuine failures beside them are (R14). W6 and W7 each fail R14 for their tool.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 11. Verified Against Codebase (the Architect read these lines 2026-11-16 on `2b7cb33001a64681c6d30e526fd0af6247d1c659`, tree `d837f4cf`, in the read-only scratch tree `G:\rev-tmp-b4r2\cand`; they were re-checked 2026-11-16 on `e0843f4f`, tree `2e8120b8`, by the orchestrator and the Architect, as the last lines of the block list)

```
file_access.py:47-49  import re / import stat / from collections.abc import Iterable, Iterator, Sequence
file_access.py:57     logger = logging.getLogger(__name__)
file_access.py:312    def resolve_read_path(   :362 resolved = candidate.resolve()   :370 on_disk = _OnDisk(base_file)
file_access.py:653    class ReadFloor:   :657-660 __init__ (three attributes; :660 _permitted may be None)   :662-673 permits (FileAccessDenied -> False)
file_access.py:796-797 @lru_cache(maxsize=1) def _windows_file_api; calls :823, :847 (search below: 5 lines)
file_access.py:203    "Pure: it calls no filesystem function" (reader_spelling)
file_search.py:112    async def _search_files(   :128 from probos.security.file_access import ReadFloor, resolve_for_runtime
file_search.py:140-154 walk, ReadFloor, kept, logger.info   :161-162 except Exception as e: / return {...}
file_walk.py:47       DEFAULT_MAX_FILES: int = 20000   :186 if yielded >= max_files:
code_search.py:23     import asyncio   :128 "max_results": max(1, min(max_results, 5000))
code_search.py:155-166 act: floor, rg, _within_floor x2   :198 check_at(... EFFECT_SUBPROCESS ...)
code_search.py:212-248 returncode check, parse loop, floor.permits (:227), BF-895 warning, rg result
code_search.py:297-306 python result dict / def _text_lines(fp: Path) -> Iterator[tuple[int, str]]:
code_search.py:323    class _ReadFloor:   :343 self._decided   :362 def _within_floor
tools.py:11-14        from __future__ / import ctypes / import hashlib   :1341 import asyncio as _asyncio (search below: 1 line)
tools.py:56-67        from probos.security.file_access import (... workspace_exempt_roots,) / from probos.tools.protocol import (
tools.py:81           _PROJECT_ROOT = Path(__file__).resolve().parents[3]   :247-250 _resolve_path
tools.py:512-519      _LIST_FILES_PATTERN_REFUSAL / class ListFilesTool:   :533-535 docstring end
tools.py:582-598      per-match loop   :1069, :1166 captain_document_write_refusal(path_text, _PROJECT_ROOT)
file_writer.py:120, :167   captain_document_write_refusal(str(p), Path.cwd())
skill_framework.py:214, :274, :429, :562   captain_document_write_refusal(..., Path.cwd()); :217 raise PermissionError(refused)
builder_paths.py:83   def _canonical   :216-234 CAPTAIN_DOCUMENT_PATHS   :242-247 _captain_document_refusal
builder_paths.py:257-259 _running_checkout   :269-278 _document_parts   :281-292 _names_a_document
builder_paths.py:426  def captain_document_write_refusal   :437-439 docstring end   :448-453 the two document checks
standing_orders.py:35 _DEFAULT_ORDERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "standing_orders"
__main__.py:4187-4188 from dotenv import load_dotenv / load_dotenv()
d:/ProbOS/.venv/Lib/site-packages/dotenv/main.py:332-372 find_dotenv: frame file's directory (cwd if usecwd/interactive/debugger/frozen), _walk_to_root
d:/ProbOS/.venv/Lib/site-packages/__editable__.probos-0.1.0.pth: D:\ProbOS\src
scripts/run_test_gate.py:818  env["PYTHONPATH"] = source_root
native_builder.py:47-57 _HARNESS_TOOL_IDS_BUILD (... "edit_file", "write_file", "list_files" ...)
worktree_manager.py:44 self._worktree_base = self._repo_root.parent / "ProbOS-builders"
substrate/agent.py:55 self._runtime: Any = kwargs.get("runtime")
pyproject.toml:9 requires-python = ">=3.12"   :181 asyncio_mode = "auto"
DECISIONS.md:1855 ### AD-1346 M3e4d9 -- part (a) ...   PROGRESS.md:1 # ProbOS Progress

Re-checked 2026-11-16 on e0843f4f by the orchestrator: the five base blobs match; file_access.py:653-673, :362, :370,
  :658-660, :796-797; file_search.py:112 (no await in :112-162); code_search.py:155-166, :227, :285, :323, :343, :362, :378;
  tools.py:81, :247-250, :582-598, :1069, :1166; builder_paths.py:83, :257, :269, :281, :426, :448-453;
  __main__.py:4187-4188; file_walk.py:47; file_writer.py:120, :167; skill_framework.py:214, :274, :429, :562;
  dotenv/main.py:332 find_dotenv; the venv .pth holds D:\ProbOS\src; ListFilesTool.description is a class string.
  git grep -n set_default_executor e0843f4f -- src                     -> 1 line, src/probos/audio/tts/resident.py:20 (module docstring)
  git grep -n -o -E "tests/fixtures/[A-Za-z0-9_]+\.py" e0843f4f -- ui -> 4 distinct files (Absence Verified)
  swe_harness/tool_call.py:20 from probos.cognitive.swe_harness.tools import InstructionToolResult
Re-checked 2026-11-16 by the Architect:
  git show e0843f4f:tests/fixtures/ad1152_agentic_off_golden.json | grep -n "list_files"           -> 1 line, :845
  git show e0843f4f:src/probos/security/file_access.py | grep -n -E "lru_cache|_windows_file_api\("  -> 5 lines, :53 :796 :797 :823 :847
  git show e0843f4f:src/probos/cognitive/swe_harness/tools.py | grep -n -E "^\s*import asyncio|^\s*from asyncio"  -> 1 line, :1341
  git show e0843f4f:src/probos/substrate/file_walk.py | grep -c -E "lru_cache|global |threading"   -> 0
  git show e0843f4f:src/probos/substrate/safe_regex.py | grep -c -E "lru_cache|global |threading"  -> 0
  Grep "ReadFloor|_ReadFloor|_within_floor|_search_python|_search_rg" tests/test_bf908_floor_and_children.py
    (a worktree copy that git diff --name-only e0843f4f HEAD does not list)                        -> 19 lines
Read 2026-11-16 by the Architect on ecec9031 (tree dca4f150) for R2:
  tools.py:1056 tool_id "write_file"  :1097-1108 the three refusals  :1142 write_file failed:  :83 _PROJECT_ROOT  :249 def _resolve_path
  tools.py:1148 tool_id "edit_file"   :1194-1205 the three refusals  :1267 File not found:  :1271 edit_file failed:
  tools.py:472 f"read_file refused: {exc}"   :621 f"list_files refused: {exc}"
  protocol.py:99-103 POLICY_REFUSAL_MARK = " refused: "   :106-115 is_caller_input_error
  fault_report.py:398-401 skip   fault_detection.py:296 skip, :308-309 same_run count, :312-317 noise filter, :331-346 ToolFaultBatch
  native_builder.py:189, agentic_dispatch.py:4450 classify_error=classify_tool_fault_error; agentic_dispatch.py:2161, :4409
  tool_call.py:670 ToolCallRequest, :680 ToolCallResult, :696 from_tool_result   effect_broker.py:920-928 error is not None only
  file_access.py:74-77 PROTECTED_LEAF_NAMES   code_search.py act: to_thread(_final_check, ...); _search_rg: to_thread(_rg_result, ...) after the subprocess
```

## Absence Verified (2026-11-16)

```
CLAIM: no default executor is replaced         RUN: git grep -n set_default_executor e0843f4f -- src   FOUND: 1 line, audio/tts/resident.py:20 (a module docstring line)   HOLDS
CLAIM: no test pins the documents list or text RUN: Grep "governance, instruction|which an agent does not write|Captain document write refused|CAPTAIN_DOCUMENT_PATHS|_CAPTAIN_DOCUMENT_PARTS" tests ui scripts config
                                               FOUND: test_bf943:1 (docstring), :260 (absence check); test_ad1344:540,581,630,721 (comments)   HOLDS
CLAIM: no test writes into a package via the eight sites  RUN: Grep "(write_file|edit_file|commit_write|output_path).{0,80}probos[/\\]" tests; Grep "path": "probos  FOUND: none   HOLDS
CLAIM: no config field for the cap             RUN: Grep "max_files|list_files" config.py, config_models/, config/
                                               FOUND: 1 line, config_models/experience.py:318, a description string that names list_files among tools, not a field   HOLDS (no field)
CLAIM: new names are free                      RUN: Grep _listed_matches|_LIST_FILES_MAX_MATCHES|_admitted_matches|_rg_result|_final_check|_search_python_checked (src, tests); _names_running_code|_RUNNING_PACKAGE|_running_code_refusal (src); if runtime is None|_NO_RUNTIME (file_access.py)
                                               FOUND: only unrelated test names containing "final_check"/"rg_result"   HOLDS
CLAIM: no ui-spawned fixture names a changed module or tool
  RUN:   git grep -n -o -E "tests/fixtures/[A-Za-z0-9_]+\.py" e0843f4f -- ui   -> 4 distinct files: ad1174_progress_bridge.py,
         approval_ui_bridge.py, consulted_evidence_bridge.py, issue1375_work_state_bridge.py; in those four,
         builder_paths|file_access|code_search|file_search|list_files|write_file|search_files
  FOUND: 0 lines   HOLDS
  With swe_harness added to the pattern: 3 lines, the imports ad1174_progress_bridge.py:20 (swe_harness.tool_call),
  :274 (swe_harness.agentic_loop) and consulted_evidence_bridge.py:32 (swe_harness.tool_call). swe_harness/tool_call.py:20
  imports swe_harness.tools, so these fixtures load the tools.py that M2a changes.
CLAIM: to_thread is not patched for these modules  RUN: Grep setattr(...to_thread tests   FOUND: test_ad818a*/a2 (episodic)   HOLDS
CLAIM: nothing in src reads the start of a write_file or edit_file error (R2)
  RUN:   git grep -n -E "[\"'](write_file|edit_file) (failed|refused)" ecec9031 -- src/probos; git grep -n is_caller_input_error ecec9031 -- src/probos
  FOUND: 2 lines for the first, both producers of failure texts: tools.py:1142, :1271. 6 lines for the second: fault_detection.py:24 (import), :296 (call); fault_report.py:49 (import), :360 (docstring), :401 (call); protocol.py:106 (definition)   HOLDS
CLAIM: no test compares the documents rule's refusal text whole, or builds the unmarked return (R2)
  RUN:   git grep -n -E "(write_file|edit_file) (failed|refused)" ecec9031 -- tests; git grep -n -E "Captain document|captain_document_refused" ecec9031 -- tests; git grep -n "error=refused" ecec9031 -- tests
  FOUND: 2 lines for the first (test_bf911:644-645, failure prefixes by startswith); 4 lines for the second (test_ad1189_deferred_tool_schemas.py:789, an unrelated page title; test_bf943:71, an assert message; :776, a log line; this file :282, a log line); 0 for the third. The refusal checks in test_bf943, test_ad1344 and test_bf911 are substring checks (_BF in, _AD in): test_bf943:120, :725, :740, :749, :760, :774; test_ad1344:469   HOLDS
REPRODUCED 2026-11-16 on e0843f4f by the orchestrator: the documents-list, writes-into-a-package, config, new-names, patched-to_thread and set_default_executor searches above.
```

## 12. Prior Art and Blind Spots

- **Internal.**
  - BF-943 (the rule and its two-form judgement), BF-911 and AD-1344 (its siblings), BF-953 (identity comparison on the read side; not adopted for writes, L7), BF-908 A4 (the fresh final floor, kept).
  - AD-481's sealed modules: the builder's lane, not agent writers.
  - AD-1316's effect authority denies a native file write under `protected_installation_root` when one is configured (`authority.py:1841-1848`; default `""`, `config.py:3867`). It acts only on calls the broker prepares (`effect_broker.py:259-268`), so the eight sites still need the rule.
- **External.**
  - python-dotenv's `find_dotenv`, read from the installed source (D7).
  - Python's `asyncio.to_thread` and `ThreadPoolExecutor` defaults (D2).
  - No web search: these are fixes to ProbOS plumbing. `docs/research/reference-projects.md` was not consulted, under the bug-fix exemption.
- **Blind spots found:**
  - `<checkout>/src/.env` takes precedence over `<checkout>/.env` (D7).
  - On the base, the native build loop's write_file and edit_file reached the live package (D10).
  - Focused runs in a worktree without `PYTHONPATH` import the main checkout's package (D6).
  - Share spellings (L7) and hard links (L4).
  - Found by review round 1, not by this contract: write_file and edit_file gave the documents rule's refusal unmarked, so the fault detectors counted it as a broken tool; this batch added refusals that a build model reaches by a relative `probos/...` path (D14). The two sibling refusals at those sites are L9.
